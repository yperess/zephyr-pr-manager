import difflib
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


def cleanup_commit_message(message: str) -> str:
    new_message = re.sub(kPrMatcher, "", message)
    new_message = re.sub(kDepsMatcher, "", new_message)
    return new_message.strip()


def debug_print_diff(name: str, diff: git.Diff) -> None:
    logging.debug("%s=%s", name, str(diff).replace(__old="\n", __new="\n        "))
    if diff.a_blob is not None and diff.b_blob is not None:
        differ = difflib.Differ()
        a = str(diff.a_blob.data_stream.read().decode('utf-8')).splitlines(keepends=False)
        b = str(diff.b_blob.data_stream.read().decode('utf-8')).splitlines(keepends=False)
        for diff in differ.compare(a, b):
            if diff.startswith("  "):
                continue
            logging.debug(diff)


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
        repo.git.commit("--amend", "-m", cleanup_commit_message(self.commit.message))

    def __eq__(self, other):
        if isinstance(other, git.Commit):
            commit_message_changed = cleanup_commit_message(self.commit.message) != cleanup_commit_message(other.message)
            if commit_message_changed:
                logging.debug("Commit message 1:\n%s", cleanup_commit_message(self.commit.message))
                logging.debug("Commit message 2:\n%s", cleanup_commit_message(other.message))
                return False

            diff1 = self.commit.repo.git.diff(f"{self.commit.parents[0].hexsha}..{self.commit.hexsha}", "--no-color")
            diff2 = self.commit.repo.git.diff(f"{other.parents[0].hexsha}..{other.hexsha}", "--no-color")
            if diff1 != diff2:
                logging.debug("Commit change detected:\n<<<<<<<<<<\n%s\n>>>>>>>>>>\n%s", diff1, diff2)
                return False
            return True
        if isinstance(other, CommitNode):
            return self == other.commit
        return False

    def __ne__(self, other):
        return not self.__eq__(other=other)

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
