"""Redaction for values that must not reach logs.

A container inventory number looks like an opaque token but is not: Ekonovus'
public Power BI API resolves one to the street address it serves, with no
authentication. Since GitHub Actions logs are world-readable on a public
repository, logging a container id in full would publish the household's
address. Everything user-facing therefore logs the redacted form.
"""

from __future__ import annotations

VISIBLE_SUFFIX = 2
MASK = "***"


def redact(value: str) -> str:
    """Mask a container id, keeping enough to be recognisable in logs.

    ``10-S-000000`` becomes ``10-S-***00``: the provider prefix stays readable so
    logs remain useful, while the digits that identify the container do not.
    """
    if not value:
        return value

    suffix = value[-VISIBLE_SUFFIX:]
    head, separator, _ = value.rpartition("-")
    if separator:
        return f"{head}-{MASK}{suffix}"
    return f"{MASK}{suffix}"
