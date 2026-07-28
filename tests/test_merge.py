from datetime import date

from trash_calendar.merge import merge
from trash_calendar.models import Collection


def test_single_container_produces_one_event_naming_it():
    events = merge([Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė")])
    assert len(events) == 1
    assert events[0].date == date(2026, 8, 6)
    assert "Pakuotė" in events[0].summary


def test_same_day_containers_merge_into_one_event():
    events = merge(
        [
            Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas", "kas 84 dienas"),
            Collection(date(2026, 8, 27), "10-P-000000", "ekonovus", "Pakuotė", "kas 21 dieną"),
        ]
    )
    assert len(events) == 1
    assert "Stiklas" in events[0].summary
    assert "Pakuotė" in events[0].summary


def test_different_days_stay_separate_and_sorted():
    events = merge(
        [
            Collection(date(2026, 9, 17), "10-P-000000", "ekonovus", "Pakuotė"),
            Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė"),
        ]
    )
    assert [e.date for e in events] == [date(2026, 8, 6), date(2026, 9, 17)]


def test_description_lists_container_ids_providers_and_cadence():
    events = merge(
        [Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė", "kas 21 dieną")]
    )
    description = events[0].description
    assert "10-P-000000" in description
    assert "ekonovus" in description
    assert "kas 21 dieną" in description


def test_duplicate_collections_do_not_duplicate_labels():
    same = Collection(date(2026, 8, 6), "10-P-000000", "ekonovus", "Pakuotė")
    events = merge([same, same])
    assert events[0].summary.count("Pakuotė") == 1


def test_labels_are_ordered_deterministically():
    a = merge(
        [
            Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas"),
            Collection(date(2026, 8, 27), "10-P-000000", "ekonovus", "Pakuotė"),
        ]
    )
    b = merge(
        [
            Collection(date(2026, 8, 27), "10-P-000000", "ekonovus", "Pakuotė"),
            Collection(date(2026, 8, 27), "10-S-000000", "ekonovus", "Stiklas"),
        ]
    )
    assert a[0].summary == b[0].summary


def test_empty_input_produces_no_events():
    assert merge([]) == []


def test_containers_from_different_providers_merge_on_the_same_day():
    events = merge(
        [
            Collection(date(2026, 8, 19), "10-MK-000000", "svara", "Mišrios komunalinės"),
            Collection(date(2026, 8, 19), "10-P-000000", "ekonovus", "Pakuotė"),
        ]
    )
    assert len(events) == 1
    assert "svara" in events[0].description
    assert "ekonovus" in events[0].description
