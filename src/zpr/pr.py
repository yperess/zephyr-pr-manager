import git
import logging

from zpr.commit import CommitNode


class PullRequestNode:
    commits: list[CommitNode]
    tag: str

    def __init__(self, tag: str):
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

    def push(self, repo: git.Repo, upstream_head: git.Head, remote: git.Remote):
        upstream_head.checkout()
        # Delete the branch if exists
        logging.info("Creating a clean branch: %s", self.branch_name)
        if self.branch_name in map(lambda branch: branch.name, repo.branches):
            repo.git.branch("-D", self.branch_name)
        repo.git.checkout("-b", self.branch_name)
        for commit in reversed(self.commits):
            commit.cherry_pick(repo)
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
            title = commit.commit.message.split("\n")[0]
            string += f"\n    {commit.commit.hexsha}: {title}"
        return string
