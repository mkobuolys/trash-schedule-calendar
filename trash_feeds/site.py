"""Write the static site: page, feeds, container lookup and manifest."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

from trash_feeds.feeds import shard_of
from trash_feeds.ics import render_feed, render_retired
from trash_feeds.models import Feed

MANIFEST = "manifest.json"
STATIC_DIR = Path(__file__).resolve().parent.parent / "site"


class ManifestError(RuntimeError):
    pass


def previous_feed_ids(site_url: str, session: requests.Session | None = None) -> set[str]:
    """Feed ids the live site publishes now, so none of them ever disappears.

    A 404 means the site has never been published. Any other failure aborts:
    publishing without the old ids would delete feeds people subscribe to.
    """
    session = session or requests.Session()
    try:
        response = session.get(f"{site_url}/{MANIFEST}", timeout=60)
    except requests.RequestException as exc:
        raise ManifestError(f"could not fetch the live manifest: {exc}") from exc
    if response.status_code == 404:
        return set()
    if not response.ok:
        raise ManifestError(f"live manifest answered HTTP {response.status_code}")
    try:
        return set(response.json()["feeds"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"live manifest is malformed: {exc!r}") from exc


def write_site(
    out: Path,
    feeds: list[Feed],
    lookup: dict[str, str],
    retired: set[str],
    site_url: str,
    today: date,
    stamp: datetime,
    static_dir: Path = STATIC_DIR,
) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(static_dir, out)

    feed_dir = out / "feeds"
    feed_dir.mkdir()
    for feed in feeds:
        (feed_dir / f"{feed.id}.ics").write_bytes(render_feed(feed, site_url, stamp))
    for feed_id in retired:
        (feed_dir / f"{feed_id}.ics").write_bytes(render_retired(feed_id, site_url, today, stamp))

    shards: dict[str, dict[str, str]] = defaultdict(dict)
    for container, feed_id in lookup.items():
        shards[shard_of(container)][container] = feed_id
    lookup_dir = out / "lookup"
    lookup_dir.mkdir()
    for shard, entries in shards.items():
        (lookup_dir / f"{shard}.json").write_text(
            json.dumps(dict(sorted(entries.items())), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    manifest = {
        "generated": stamp.isoformat(),
        "feeds": sorted({feed.id for feed in feeds} | retired),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=0), encoding="utf-8")
