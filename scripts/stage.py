"""Derives the stage name from a branch name: one short-lived stage per branch, prod for main.

Lowercase, only a-z, 0-9 and '-', at most 20 characters. A shortened name gets a hash suffix so
that two long branches with the same prefix do not end up on the same stage.

    python scripts/stage.py                    # current git branch
    python scripts/stage.py feature/Foo_Bar    # -> feature-foo-bar
"""

import hashlib
import re
import subprocess
import sys

MAX_LENGTH = 20
HASH_LENGTH = 6
PRODUCTION_BRANCH = "main"
PRODUCTION_STAGE = "prod"


def stage_from_branch(branch: str) -> str:
    if branch == PRODUCTION_BRANCH:
        return PRODUCTION_STAGE
    name = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-") or "stage"
    # Only main deploys to prod. A branch that happens to be called "prod" gets a hash suffix.
    if name == PRODUCTION_STAGE:
        name = f"{name}-{hashlib.sha256(branch.encode()).hexdigest()[:HASH_LENGTH]}"
    if len(name) <= MAX_LENGTH:
        return name
    digest = hashlib.sha256(branch.encode()).hexdigest()[:HASH_LENGTH]
    return f"{name[: MAX_LENGTH - HASH_LENGTH - 1].rstrip('-')}-{digest}"


def current_branch() -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True, check=True
    ).stdout.strip()


if __name__ == "__main__":
    print(stage_from_branch(sys.argv[1] if len(sys.argv) > 1 else current_branch()))
