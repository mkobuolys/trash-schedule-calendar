"""Container ids must never reach logs in full.

A container id is not an opaque token: Ekonovus' public API resolves one to the
street address it belongs to, without authentication. Public CI logs therefore
must not carry them.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
import yaml

from trash_calendar import cli
from trash_calendar.models import Collection
from trash_calendar.redact import redact

CONFIG = {
    "calendar_id": "cal-1",
    "containers": [{"provider": "ekonovus", "id": "10-S-000000"}],
}


def test_redact_keeps_the_prefix_and_last_two_characters():
    assert redact("10-S-000000") == "10-S-***00"


def test_redact_handles_a_longer_id():
    assert redact("10-MK-000000") == "10-MK-***00"


def test_redact_does_not_leak_a_short_id_either():
    assert "1234" not in redact("1234")


def test_redact_tolerates_an_id_without_separators():
    assert redact("ABCDEFGH").endswith("GH")
    assert "ABCDEF" not in redact("ABCDEFGH")


def test_redact_passes_through_empty_values():
    assert redact("") == ""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG, allow_unicode=True), encoding="utf-8")
    return path


class StubProvider:
    name = "ekonovus"

    def fetch(self, container, horizon):
        return [Collection(date(2026, 8, 27), container.id, "ekonovus", "Stiklas")]


class StubSync:
    def plan(self, events, horizon):
        from trash_calendar.gcal import SyncPlan

        return SyncPlan(
            to_create=[
                {"summary": e.summary, "start": {"date": e.date.isoformat()}} for e in events
            ]
        )

    def apply(self, plan, dry_run=False):
        return None


def test_cli_never_logs_a_raw_container_id(monkeypatch, config_file, caplog):
    monkeypatch.setattr(cli, "get_provider", lambda name: StubProvider())
    monkeypatch.setattr(cli, "build_sync", lambda config, offline=False: StubSync())

    with caplog.at_level(logging.DEBUG, logger="trash_calendar"):
        assert cli.main(["--config", str(config_file), "--dry-run", "--verbose"]) == 0

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert logged, "expected the CLI to log something"
    assert "10-S-000000" not in logged
    assert "10-S-***00" in logged


def test_cli_redacts_container_ids_in_failure_messages(monkeypatch, config_file, caplog):
    from trash_calendar.models import ProviderError

    class Broken:
        name = "ekonovus"

        def fetch(self, container, horizon):
            raise ProviderError(f"no schedule for container {redact(container.id)!r}")

    monkeypatch.setattr(cli, "get_provider", lambda name: Broken())
    monkeypatch.setattr(cli, "build_sync", lambda config, offline=False: StubSync())

    with caplog.at_level(logging.DEBUG, logger="trash_calendar"):
        assert cli.main(["--config", str(config_file)]) == 1

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "10-S-000000" not in logged
