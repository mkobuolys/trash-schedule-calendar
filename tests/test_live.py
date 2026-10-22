from __future__ import annotations

import pytest

from trash_feeds.cli import MIN_CONTAINERS, MIN_SCHEDULES
from trash_feeds.ekonovus import fetch_containers, fetch_schedules
from trash_feeds.powerbi import Client

pytestmark = pytest.mark.live


def test_full_export_is_plausible():
    client = Client()
    schedules = fetch_schedules(client)
    containers = fetch_containers(client)

    assert len(schedules) >= MIN_SCHEDULES
    assert len(containers) >= MIN_CONTAINERS
    assert sum(1 for c in containers if c.schedule_ids & schedules.keys()) >= MIN_CONTAINERS
