import git
import logging

from zpr.commit import CommitNode


class PullRequestNode:
    repo: git.Repo
    commits: list[CommitNode]
    tag: str

    def __init__(self, repo: git.Repo, tag: str):
        self.repo = repo
        self.commits = []
        self.tag = tag

    def add_commit(self, commit: CommitNode):
        self.commits.append(commit)

    @property
    def branch_name(self) -> str:
        return f"push-bot/{self.tag}"

    @property
    def dependencies(self) -> list[str]:
        dependencies: set[str] = set()
        for commit in self.commits:
            dependencies.update(commit.dependencies)
        return list(dependencies)

    def push(self, upstream_head: git.Head, remote: git.Remote | None):
        if not self.__check_needs_push():
            logging.info("Skipping push for %s, no changes detected", self.tag)
            return
        upstream_head.checkout()
        # Delete the branch if exists
        logging.info("Creating a clean branch: %s", self.branch_name)
        if self.branch_name in map(lambda branch: branch.name, self.repo.branches):
            self.repo.git.branch("-D", self.branch_name)
        self.repo.git.checkout("-b", self.branch_name)
        for commit in reversed(self.commits):
            commit.cherry_pick(self.repo)

        if remote is not None:
            logging.info("Pushing to %s/%s", remote.name, self.branch_name)
            remote.push(refspec=f"{self.branch_name}:{self.branch_name}", force=True)

    def __check_needs_push(self) -> bool:
        branch: git.Head | None = None
        for b in self.repo.branches:
            if self.branch_name == b.name:
                branch = b
                break

        if branch is None:
            return True

        # Checkout the existing branch
        branch.checkout()
        head = branch.commit
        for pending_commit in self.commits:
            logging.debug("Comparing %s vs. %s", pending_commit.commit.hexsha, head.hexsha)
            if pending_commit != head:
                return True
            if len(head.parents) == 0:
                return True
            head = head.parents[0]
        return False

    def __str__(self):
        deps = self.dependencies
        string = f"Branch name: {self.branch_name}\nDepends on: "
        if deps:
            string += ",".join(deps)
        else:
            string += "None"
        string += "\nCommits:"
        for commit in self.commits:
            title = commit.commit.message.split("\n")[0]
            string += f"\n    {commit.commit.hexsha}: {title}"
        return string
