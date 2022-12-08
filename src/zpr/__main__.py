# SPDX-License-Identifier: Apache-2.0

import argparse
import git
import logging
import os
import pathlib

from zpr.commit import CommitNode
from zpr.pr import PullRequestNode

kZephyrRemoteUrls = ["https://github.com/zephyrproject-rtos/zephyr",
                     "git@github.com:zephyrproject-rtos/zephyr.git"]


def selection_to_bool(selection: str) -> bool:
    selection = selection.lower()
    return selection == "y" or selection == "yes"


# noinspection PyShadowingBuiltins
def resolve_repo() -> git.Repo | None:
    dir = pathlib.Path(os.getcwd())
    while dir is not None and dir.is_dir():
        try:
            repo = git.Repo(path=dir)
            return repo
        except git.InvalidGitRepositoryError:
            pass
        dir = dir.parent
    return None


class CommitList:
    commits: list[CommitNode]

    def __init__(self, repo: git.Repo, zephyr_remote_name: str):
        # Get all commits until we reach one that is already in the Zephyr tree
        self.commits = []
        for commit in repo.iter_commits(rev=repo.active_branch.name):
            branch_list = repo.git.branch("-a", "--contains", str(commit.hexsha))
            if f"remotes/{zephyr_remote_name}/main" in branch_list:
                break
            self.commits.append(CommitNode(commit))


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

    def do_run(self, dry_run: bool) -> int:
        logging.info("Parsing branch '%s'", self.repo.active_branch.name)

        # Get all commits until we reach one that is already in the Zephyr tree
        commits = CommitList(self.repo, self.zephyr_remote.name).commits

        prs: dict[str, PullRequestNode] = {}
        for commit in commits:
            if commit.tag is None:
                continue
            logging.debug("Parsing commit with tag '%s'", commit.tag)
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
            print("No viable PRs found, goodbye!")
            return 0

        if dry_run:
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

    def __resolve_remote(self) -> git.Remote | None:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="zpr",
        description="Push commits in a branch as parallel PRs in Zephyr",
        epilog="This utility searches"
    )
    parser.add_argument('--verbose', '-v', action='count', default=0,
                        help="Enables verbose logging")
    parser.add_argument('--dry-run', action='store_true',
                        help="Scans commits and prints the DAG but does not attempt to push")
    args = parser.parse_args()

    if args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    return PRManager().do_run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
