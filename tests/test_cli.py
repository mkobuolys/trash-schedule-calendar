from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from trash_feeds import cli
from trash_feeds.ekonovus import Container
from trash_feeds.models import Schedule


@pytest.fixture
def export(monkeypatch):
    soon = date.today() + timedelta(days=3)
    state = {
        "schedules": {1: Schedule(1, "kas 7 dienas", (soon,))},
        "containers": [Container("99-S-00001", "Stiklas", frozenset({1}))],
        "previous": set(),
    }
    monkeypatch.setattr(cli, "fetch_schedules", lambda client: state["schedules"])
    monkeypatch.setattr(cli, "fetch_containers", lambda client: state["containers"])
    monkeypatch.setattr(cli, "previous_feed_ids", lambda url: state["previous"])
    return state


def run(out):
    return cli.main(["--out", str(out), "--site-url", "https://example.github.io/trash/"])


def test_implausibly_small_export_fails_without_writing(tmp_path, export):
    out = tmp_path / "site"

    assert run(out) == 1
    assert not out.exists()


def test_publishes_and_keeps_feeds_that_disappeared(tmp_path, export, monkeypatch):
    monkeypatch.setattr(cli, "MIN_SCHEDULES", 1)
    monkeypatch.setattr(cli, "MIN_CONTAINERS", 1)
    export["previous"] = {"vanished"}
    out = tmp_path / "site"

    assert run(out) == 0

    manifest = json.loads((out / "manifest.json").read_text())
    assert "vanished" in manifest["feeds"]
    assert (out / "feeds" / "vanished.ics").exists()
    assert len(list((out / "feeds").glob("svara-*.ics"))) == 70
