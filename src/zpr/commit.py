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

            has_diff: bool = False
            self_diff_list: list[git.Diff] = self.commit.parents[0].diff(self.commit)
            other_diff_list: list[git.Diff] = other.parents[0].diff(other)
            if len(self_diff_list) != len(other_diff_list):
                has_diff = True
                logging.debug("Diff list has different lengths")

            if not has_diff:
                for idx, _ in enumerate(self_diff_list):
                    if self_diff_list[idx].diff != other_diff_list[idx].diff:
                        has_diff = True
                        logging.debug("Diff doesn't match betweed %s and %s",
                                      self.commit.hexsha, other.hexsha)
                        debug_print_diff("self", self_diff_list[idx])
                        debug_print_diff("other", other_diff_list[idx])
                        break
            logging.debug("has_diff=%s", has_diff)
            return not commit_message_changed and not has_diff
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
