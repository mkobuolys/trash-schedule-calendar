from __future__ import annotations

from datetime import date, timedelta

import pytest

from trash_feeds.ekonovus import Container, waste_type
from trash_feeds.feeds import (
    build_ekonovus,
    build_svara,
    feed_id,
    normalize_id,
    resolve_label,
    shard_of,
    svara_pattern_of,
)
from trash_feeds.models import Schedule

START = date(2026, 10, 22)
END = date(2027, 10, 22)


# The same vectors are asserted in tests/js/logic.test.mjs against site/logic.js.
@pytest.mark.parametrize(
    ("raw", "normalized", "shard"),
    [
        ("99-S-00001", "99-S-00001", "ec"),
        (" 99–ž-00042 ", "99-Ž-00042", "6f"),
        ("12-KAP001", "12-KAP001", "a3"),
    ],
)
def test_normalize_and_shard_match_the_page(raw, normalized, shard):
    assert normalize_id(raw) == normalized
    assert shard_of(normalized) == shard


@pytest.mark.parametrize(
    ("day", "interval", "expected"),
    [
        (date(2026, 10, 28), 2, "svara-2w-d2-p1"),
        (date(2026, 11, 4), 2, "svara-2w-d2-p0"),
        (date(2023, 12, 31), 3, "svara-3w-d6-p2"),
        (date(2026, 10, 26), 1, "svara-1w-d0-p0"),
        (date(2027, 1, 15), 4, "svara-4w-d4-p2"),
    ],
)
def test_svara_pattern_matches_the_page(day, interval, expected):
    assert svara_pattern_of(day, interval) == expected


def test_waste_type_is_read_from_the_label_suffix():
    assert waste_type("99-S-00001 (Stiklas)") == "Stiklas"
    assert waste_type("99-S-00001") is None
    assert waste_type(None) is None


@pytest.mark.parametrize(
    ("container", "expected"),
    [
        (Container("99-S-00001", "Stiklas", frozenset()), "stiklas"),
        (Container("99-L-00001", "Komunalinės", frozenset()), "mišrios komunalinės"),
        (Container("99-P-00001", None, frozenset()), "pakuotės"),
        (Container("99-L-00001", None, frozenset()), "mišrios komunalinės"),
        (Container("99-KA-00001", None, frozenset()), None),
        (Container("12-KAP001", "MT00001", frozenset()), None),
    ],
)
def test_resolve_label(container, expected):
    assert resolve_label(container) == expected


def test_feed_id_ignores_schedule_order_and_depends_on_label():
    assert feed_id("stiklas", frozenset({2, 1})) == feed_id("stiklas", frozenset({1, 2}))
    assert feed_id("stiklas", frozenset({1})) != feed_id("pakuotės", frozenset({1}))


def schedules():
    return {
        1: Schedule(1, "kas 14 dienų", (date(2026, 10, 29), date(2026, 11, 12), date(2027, 11, 1))),
        2: Schedule(2, "kas 7 dienas", (date(2026, 10, 27), date(2026, 11, 3))),
    }


def test_containers_sharing_a_schedule_share_a_feed():
    containers = [
        Container("99-S-00001", "Stiklas", frozenset({1})),
        Container("99-s-00002", "Stiklas", frozenset({1})),
        Container("99-P-00003", "Pakuotė", frozenset({1})),
    ]

    feeds, lookup = build_ekonovus(containers, schedules(), START, END)

    assert len(feeds) == 2
    assert lookup["99-S-00001"] == lookup["99-S-00002"] != lookup["99-P-00003"]
    glass = next(f for f in feeds if f.label == "stiklas")
    assert glass.dates == (date(2026, 10, 29), date(2026, 11, 12))
    assert glass.cadence == "kas 14 dienų"
    assert glass.calendar_name == "Šiukšlės: stiklas (Ekonovus)"
    assert glass.summary == "🗑️ Išstumti: stiklas"


def test_multi_schedule_containers_merge_dates_and_cadences():
    feeds, _ = build_ekonovus(
        [Container("99-L-00001", "Komunalinės", frozenset({1, 2}))], schedules(), START, END
    )
    assert feeds[0].dates == (
        date(2026, 10, 27),
        date(2026, 10, 29),
        date(2026, 11, 3),
        date(2026, 11, 12),
    )
    assert feeds[0].cadence == "kas 14 dienų + kas 7 dienas"


def test_containers_without_future_schedules_are_left_out():
    feeds, lookup = build_ekonovus(
        [Container("99-S-00001", "Stiklas", frozenset({404}))], schedules(), START, END
    )
    assert feeds == []
    assert lookup == {}


def test_unlabelled_feed_has_generic_wording():
    feeds, _ = build_ekonovus([Container("99-KA-1", None, frozenset({2}))], schedules(), START, END)
    assert feeds[0].summary == "🗑️ Išstumti konteinerį"
    assert feeds[0].calendar_name == "Šiukšlių išvežimas (Ekonovus)"


def test_svara_covers_every_weekday_interval_and_phase():
    feeds = build_svara(START, END)

    assert len(feeds) == 7 * (1 + 2 + 3 + 4)
    assert len({f.id for f in feeds}) == len(feeds)
    for feed in feeds:
        interval = int(feed.id.split("-")[1].rstrip("w"))
        assert feed.dates[0] >= START
        assert feed.dates[0] < START + timedelta(weeks=interval)
        assert feed.dates[-1] < END
        assert all(
            b - a == timedelta(weeks=interval)
            for a, b in zip(feed.dates, feed.dates[1:], strict=False)
        )
        assert all(svara_pattern_of(d, interval) == feed.id for d in feed.dates)
