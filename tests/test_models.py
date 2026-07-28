from datetime import date

from trash_calendar.models import Collection, DateRange


def test_date_range_from_months_spans_horizon():
    r = DateRange.from_months(date(2026, 7, 28), 6)
    assert r.start == date(2026, 7, 28)
    assert r.end == date(2027, 1, 28)


def test_date_range_from_months_wraps_year_end():
    r = DateRange.from_months(date(2026, 11, 15), 6)
    assert r.end == date(2027, 5, 15)


def test_date_range_contains_is_inclusive():
    r = DateRange(date(2026, 8, 1), date(2026, 8, 31))
    assert r.contains(date(2026, 8, 1))
    assert r.contains(date(2026, 8, 31))
    assert not r.contains(date(2026, 7, 31))
    assert not r.contains(date(2026, 9, 1))


def test_date_range_years_lists_each_calendar_year_touched():
    assert DateRange(date(2026, 11, 1), date(2027, 3, 1)).years() == [2026, 2027]
    assert DateRange(date(2026, 2, 1), date(2026, 8, 1)).years() == [2026]


def test_collection_is_hashable_for_deduplication():
    a = Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė", "kas 21 dieną")
    b = Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė", "kas 21 dieną")
    assert len({a, b}) == 1
