# SPDX-License-Identifier: Apache-2.0

import argparse
import os
import re
import sys

import git
import logging
import pathlib

kZephyrRemoteUrls = ["https://github.com/zephyrproject-rtos/zephyr", "git@github.com:zephyrproject-rtos/zephyr.git"]
kPrMatcher = re.compile("^topic#(\\w+)$", re.IGNORECASE | re.MULTILINE)
kDepsMatcher = re.compile("^topic-deps:((?:\\s*topic#\\w+[,\\s]*)+)$", re.IGNORECASE | re.MULTILINE)


def get_tag(string: str):
    match = kPrMatcher.search(string)
    if match is None:
        return None
    assert len(match.groups()) == 1, f"Expected only one tag, found {len(match.groups())}"
    return match.groups()[0]


def selection_to_bool(selection: str):
    selection = selection.lower()
    return selection == "y" or selection == "yes"


class CommitNode:
    commit: git.Commit
    tag: str
    dependencies: list[str]

    def __init__(self, commit: git.Commit):
        self.commit = commit
        self.dependencies = []
        self.__parse_commit_message()

    def __parse_commit_message(self):
        self.tag = get_tag(self.commit.message)
        if self.tag is None:
            return

        match = kDepsMatcher.search(self.commit.message)
        if match is None:
            return
        assert len(match.groups()) == 1, f"Expected only one dependency line per commit, found {len(match.groups())}"
        for dependency in str(match.groups()[0]).strip().split(sep=","):
            self.dependencies.append(get_tag(dependency.strip()))

    def __str__(self):
        string = f"tag: {self.tag}\ndeps: "
        if self.dependencies:
            string += ','.join(self.dependencies)
        else:
            string += "None"
        string += "\n\n>   " + self.commit.message.replace("\n", "\n>   ")
        return string


class PullRequestNode:
    commits: list[CommitNode]
    tag: str

    def __init__(self, tag: str):
        self.tag = tag
        self.commits = []

    def add_commit(self, commit: CommitNode):
        self.commits.append(commit)

    @property
    def branch_name(self):
        return f"push-bot/{self.tag}"

    @property
    def dependencies(self):
        dependencies: set[str] = set()
        for commit in self.commits:
            dependencies.update(commit.dependencies)
        return list(dependencies)

    def push(self, repo: git.Repo, upstream_head: git.Head, remote: git.Remote):
        upstream_head.checkout()
        # Delete the branch if exists
        logging.info("Creating a clean branch: %s", self.branch_name)
        if self.branch_name in map(lambda branch: branch.name, repo.branches):
            repo.git.branch("-D", self.branch_name)
        repo.git.checkout("-b", self.branch_name)
        for commit in self.commits:
            logging.info("Cherry picking %s", commit.commit.hexsha)
            try:
                repo.git.cherry_pick(commit.commit.hexsha)
            except Exception as err:
                repo.git.cherry_pick("--abort")
                raise err
        logging.info("Pushing to %s/%s", remote.name, self.branch_name)
        remote.push(refspec=f"{self.branch_name}:{self.branch_name}", force=True)

    def __str__(self):
        deps = self.dependencies
        string = f"Branch name: {self.branch_name}\nDepends on: "
        if deps:
            string += ",".join(deps)
        else:
            string += "None"
        string += "\nCommits:"
        for commit in self.commits:
            string += f"\n    {commit.commit.hexsha}"
        return string


def resolve_repo():
    dir = pathlib.Path(os.getcwd())
    while dir is not None and dir.is_dir():
        try:
            repo = git.Repo(path=dir)
            return repo
        except git.InvalidGitRepositoryError:
            pass
        dir = dir.parent


class PRManager:
    repo: git.Repo
    original_branch: git.Head
    zephyr_main_branch: git.Head

    def __init__(self):
        self.repo = resolve_repo()
        assert self.repo is not None, f"Cannot find git repo in {os.getcwd()}"
        self.original_branch = self.repo.active_branch
        for remote in self.repo.remotes:
            if remote.url in kZephyrRemoteUrls:
                self.zephyr_remote = remote
                break
        assert self.zephyr_remote is not None
        for branch in self.repo.branches:
            if str(branch.tracking_branch()) == str(f"{self.zephyr_remote.name}/main"):
                self.zephyr_main_branch = branch.tracking_branch()
                break
        assert self.zephyr_main_branch is not None

    def do_run(self):
        logging.info("Parsing branch '%s'", self.repo.active_branch.name)

        commits: list[CommitNode] = []
        for commit in self.repo.iter_commits(rev=self.repo.active_branch.name):
            branch_list = self.repo.git.branch("-a", "--contains", str(commit.hexsha))
            if f"remotes/{self.zephyr_remote.name}/main" in branch_list:
                break
            node = CommitNode(commit)
            if node.tag is not None:
                commits.append(node)

        prs: dict[str, PullRequestNode] = {}
        for commit in commits:
            if commit.tag not in prs:
                prs[commit.tag] = PullRequestNode(tag=commit.tag)
            pr = prs[commit.tag]
            pr.add_commit(commit)

        print("Prepared to upload:")
        for pr in prs.values():
            if pr.dependencies:
                logging.info("Skipping %s due to dependencies", pr.tag)
                prs.pop(pr.tag)
                continue
            print("*" * 80)
            print(pr)

        if not prs:
            print("No commits found, goodbye!")
            return 0

        selection = input("Continue (y/n)? ")
        if not selection_to_bool(selection):
            print("Aborting...")
            return -1

        remote = self.__resolve_remote()
        for pr in prs.values():
            # noinspection PyBroadException
            try:
                pr.push(repo=self.repo, upstream_head=self.zephyr_main_branch, remote=remote)
            except Exception:
                logging.exception(f"Failed to push {pr.tag}")
                self.original_branch.checkout()
                return -1

        self.original_branch.checkout()
        return 0

    def __resolve_remote(self):
        if self.repo.active_branch.tracking_branch():
            remote_name = self.repo.active_branch.tracking_branch().remote_name
            remote = self.repo.remote(remote_name)
            selection = input(f"Use remote '{remote_name} ({remote.url})' (y/n)? ")
            if selection_to_bool(selection):
                return remote
        print("Branch is not currently tracking a remote branch, please select a remote:")
        remotes = list(filter(lambda remote: remote.url not in kZephyrRemoteUrls, self.repo.remotes))
        for idx, remote in enumerate(remotes):
            print(f"{idx}. {remote.name} ({remote.url})")
        selection = input(f"Select remote (0..{len(remotes) - 1}, anything else to cancel) ")
        if not selection.isdigit() or int(selection) < 0 or int(selection) >= len(remotes):
            return None
        return remotes[int(selection)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="zpr",
        description="Push commits in a branch as parallel PRs in Zephyr",
        epilog="This utility searches"
    )
    parser.add_argument('--verbose', '-v', action='count', default=0)
    args = parser.parse_args()

    if args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    sys.exit(PRManager().do_run())
