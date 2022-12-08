import git
import logging
import re

kPrMatcher = re.compile("^topic#(\\w+)$", re.IGNORECASE | re.MULTILINE)
kDepsMatcher = re.compile("^topic-deps:((?:\\s*topic#\\w+[,\\s]*)+)$", re.IGNORECASE | re.MULTILINE)


def get_tag(string: str) -> str | None:
    match = kPrMatcher.search(string)
    if match is None:
        return None
    assert len(match.groups()) == 1, f"Expected only one tag, found {len(match.groups())}"
    return match.groups()[0]


class CommitNode:
    commit: git.Commit
    tag: str
    dependencies: list[str]

    def __init__(self, commit: git.Commit):
        self.commit = commit
        self.dependencies = []
        self.__parse_commit_message()

    def cherry_pick(self, repo: git.Repo):
        logging.info("Cherry picking %s", self.commit.hexsha)
        try:
            repo.git.cherry_pick(self.commit.hexsha)
        except Exception as err:
            repo.git.cherry_pick("--abort")
            raise err
        new_message = re.sub(kPrMatcher, "", self.commit.message)
        new_message = re.sub(kDepsMatcher, "", new_message)
        repo.git.commit("--amend", "-m", new_message)

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
