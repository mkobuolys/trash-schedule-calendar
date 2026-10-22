import pytest
import yaml

from trash_calendar.config import load_config
from trash_calendar.models import ConfigError

VALID = {
    "calendar_id": "abc@group.calendar.google.com",
    "containers": [
        {"provider": "ekonovus", "id": "10-S-000000"},
        {
            "provider": "svara",
            "id": "10-MK-000000",
            "location": {
                "region": "Pavyzdžio r. sav.",
                "subdistrict": "Pavyzdžio sen.",
                "city": "Pavyzdžio mstl.",
                "street": "Pavyzdžio g.",
                "house": "1-1",
            },
        },
    ],
}


def _write(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_config_applies_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.timezone == "Europe/Vilnius"
    assert cfg.horizon_months == 6
    assert cfg.reminder_minutes_before == 360
    assert len(cfg.containers) == 2


def test_ekonovus_container_needs_no_location(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.containers[0].location is None


def test_svara_container_without_location_is_rejected_naming_the_field(tmp_path):
    data = {**VALID, "containers": [{"provider": "svara", "id": "10-MK-000000"}]}
    with pytest.raises(ConfigError) as err:
        load_config(_write(tmp_path, data))
    assert "svara" in str(err.value)
    assert "location" in str(err.value)


def test_svara_container_with_incomplete_location_names_the_missing_field(tmp_path):
    data = {
        **VALID,
        "containers": [
            {
                "provider": "svara",
                "id": "10-MK-000000",
                "location": {"region": "Pavyzdžio r. sav.", "city": "Pavyzdžio mstl."},
            }
        ],
    }
    with pytest.raises(ConfigError) as err:
        load_config(_write(tmp_path, data))
    assert "street" in str(err.value)


def test_svara_container_accepts_a_hashed_id(tmp_path):
    data = {**VALID, "containers": [{**VALID["containers"][1], "hashed_id": "AAAA1111"}]}
    assert load_config(_write(tmp_path, data)).containers[0].hashed_id == "AAAA1111"


def test_unknown_provider_is_rejected(tmp_path):
    data = {**VALID, "containers": [{"provider": "nope", "id": "1"}]}
    with pytest.raises(ConfigError) as err:
        load_config(_write(tmp_path, data))
    assert "nope" in str(err.value)


def test_missing_config_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "absent.yaml")


def test_example_config_parses_and_contains_only_placeholders():
    """The shipped example must never carry a real address or container id.

    Asserted positively — every value looks like a placeholder — rather than by
    denylisting real values, which would put them in the repo.
    """
    cfg = load_config("config.example.yaml")
    assert cfg.containers

    assert cfg.calendar_id.startswith("your-")
    for container in cfg.containers:
        digits = "".join(ch for ch in container.id if ch.isdigit())
        assert set(digits) <= {"0"}, f"container id {container.id!r} looks real"
        if container.location is None:
            continue
        for field, value in container.location:
            assert "Example" in value or value == "1-1", (
                f"location.{field} = {value!r} does not look like a placeholder"
            )
