from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from trash_feeds.feeds import shard_of
from trash_feeds.models import Feed
from trash_feeds.site import ManifestError, previous_feed_ids, write_site

STAMP = datetime(2026, 10, 22, 6, 0, tzinfo=ZoneInfo("Europe/Vilnius"))
SITE = "https://example.github.io/trash"
FEED = Feed("abc123", "Ekonovus", "stiklas", "kas 14 dienų", (date(2026, 10, 29),))


def test_writes_page_feeds_lookup_shards_and_manifest(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "stale.txt").write_text("from a previous build")

    write_site(
        out,
        [FEED],
        {"99-S-00001": "abc123"},
        {"gone"},
        SITE,
        date(2026, 10, 22),
        STAMP,
    )

    assert not (out / "stale.txt").exists()
    assert (out / "index.html").exists()
    assert (out / "logic.js").exists()
    assert (out / "feeds" / "abc123.ics").read_bytes().startswith(b"BEGIN:VCALENDAR")
    assert b"pasikeit" in (out / "feeds" / "gone.ics").read_bytes()
    shard = json.loads((out / "lookup" / f"{shard_of('99-S-00001')}.json").read_text())
    assert shard == {"99-S-00001": "abc123"}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["feeds"] == ["abc123", "gone"]


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, timeout):
        assert url == f"{SITE}/manifest.json"
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_previous_ids_come_from_the_live_manifest():
    session = FakeSession(FakeResponse(200, {"feeds": ["a", "b"]}))
    assert previous_feed_ids(SITE, session) == {"a", "b"}


def test_unpublished_site_has_no_previous_ids():
    assert previous_feed_ids(SITE, FakeSession(FakeResponse(404))) == set()


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(503),
        FakeResponse(200, ValueError("not json")),
        FakeResponse(200, {"unexpected": True}),
        requests.ConnectionError("offline"),
    ],
)
def test_unreadable_manifest_aborts_rather_than_dropping_feeds(response):
    with pytest.raises(ManifestError):
        previous_feed_ids(SITE, FakeSession(response))
