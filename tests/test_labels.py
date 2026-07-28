from datetime import date

from trash_calendar.labels import resolve_label
from trash_calendar.models import Collection


def c(container_id, label=None):
    return Collection(date(2026, 8, 6), container_id, "ekonovus", label)


def test_configured_label_wins():
    assert resolve_label(c("10-S-000000", "Stiklas"), configured="mano stiklas") == "mano stiklas"


def test_provider_label_is_used_when_config_is_silent():
    assert resolve_label(c("10-S-000000", "Stiklas")) == "Stiklas"


def test_glass_code_falls_back_to_convention():
    assert resolve_label(c("10-S-000000")) == "stiklas"


def test_packaging_code_falls_back_to_convention():
    assert resolve_label(c("10-P-000000")) == "pakuotės"


def test_mixed_municipal_code_falls_back_to_convention():
    assert resolve_label(c("10-MK-000000")) == "mišrios komunalinės"


def test_unrecognised_code_falls_back_to_the_raw_id():
    assert resolve_label(c("52-XX-1")) == "52-XX-1"
