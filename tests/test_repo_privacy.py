"""Guard against committing a real address or container id.

The repository is public. Fixtures are captured from live providers, so they
arrive full of a real address — they must be anonymised before being committed.
This test compares every tracked file against the values in the local (gitignored)
``config.yaml``, so it only has teeth on a machine that has one. That is enough:
it runs for whoever captures new fixtures, which is exactly when the leak happens.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from trash_calendar.config import Config

SKIP_FILES = {"tests/test_repo_privacy.py"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [Path(line) for line in result.stdout.splitlines() if line]


# The region is a whole municipality — too coarse to identify a household, and
# its name legitimately appears in the waste operator's own company name.
COARSE_FIELDS = {"region"}


def secrets_from(config: Config) -> set[str]:
    values: set[str] = set()
    for container in config.containers:
        values.add(container.id)
        if container.location is None:
            continue
        for field, value in container.location:
            if field in COARSE_FIELDS:
                continue
            values.add(value)
    # Sub-tokens that identify a place on their own, e.g. the street name without
    # its "g." suffix.
    for value in list(values):
        head = value.split()[0].rstrip(".,")
        if len(head) >= 5:
            values.add(head)
    return {value for value in values if len(value) >= 4}


def test_no_tracked_file_contains_a_configured_address_or_container_id(real_config):
    secrets = secrets_from(real_config)
    assert secrets, "expected the local config to yield values to check"

    offenders: list[str] = []
    for path in tracked_files():
        if str(path) in SKIP_FILES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for secret in secrets:
            if secret in text:
                offenders.append(f"{path} contains {secret!r}")

    assert not offenders, "tracked files leak real identity:\n" + "\n".join(sorted(offenders))
