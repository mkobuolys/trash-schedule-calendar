from datetime import date

import pytest
import yaml

from trash_calendar import cli
from trash_calendar.models import Collection

CONFIG = {
    "calendar_id": "cal-1",
    "containers": [{"provider": "ekonovus", "id": "10-S-000000"}],
}


class StubProvider:
    name = "ekonovus"

    def __init__(self, collections):
        self.collections = collections

    def fetch(self, container, horizon):
        return self.collections


class StubSync:
    def __init__(self):
        self.applied = []

    def plan(self, events, horizon):
        from trash_calendar.gcal import SyncPlan

        return SyncPlan(
            to_create=[
                {"summary": e.summary, "start": {"date": e.date.isoformat()}} for e in events
            ]
        )

    def apply(self, plan, dry_run=False):
        self.applied.append((plan, dry_run))


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG, allow_unicode=True), encoding="utf-8")
    return path


def _patch(monkeypatch, collections, sync):
    monkeypatch.setattr(cli, "get_provider", lambda name: StubProvider(collections))
    monkeypatch.setattr(cli, "build_sync", lambda config: sync)


def test_cli_syncs_and_exits_zero(monkeypatch, config_file):
    sync = StubSync()
    _patch(monkeypatch, [Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas")], sync)
    assert cli.main(["--config", str(config_file)]) == 0
    assert sync.applied and sync.applied[0][1] is False


def test_dry_run_does_not_apply(monkeypatch, config_file):
    sync = StubSync()
    _patch(monkeypatch, [Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas")], sync)
    assert cli.main(["--config", str(config_file), "--dry-run"]) == 0
    assert sync.applied[0][1] is True


def test_a_provider_returning_nothing_exits_non_zero(monkeypatch, config_file):
    _patch(monkeypatch, [], StubSync())
    assert cli.main(["--config", str(config_file)]) == 1


def test_source_filter_skips_other_providers(monkeypatch, config_file):
    sync = StubSync()
    _patch(monkeypatch, [Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas")], sync)
    # Filtering to a provider not in config leaves nothing to sync -> guard trips.
    assert cli.main(["--config", str(config_file), "--source", "svara"]) == 1


def test_bad_config_exits_non_zero(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("not: [a, valid, config", encoding="utf-8")
    assert cli.main(["--config", str(bad)]) == 1


def test_missing_google_credentials_exit_non_zero(monkeypatch, config_file):
    monkeypatch.setattr(
        cli, "get_provider", lambda name: StubProvider([Collection(date(2026, 8, 27), "x", "e")])
    )
    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["--config", str(config_file)]) == 1


def test_a_provider_error_exits_non_zero(monkeypatch, config_file):
    from trash_calendar.models import ProviderError

    class Broken:
        name = "ekonovus"

        def fetch(self, container, horizon):
            raise ProviderError("site changed shape")

    monkeypatch.setattr(cli, "get_provider", lambda name: Broken())
    monkeypatch.setattr(cli, "build_sync", lambda config: StubSync())
    assert cli.main(["--config", str(config_file)]) == 1
