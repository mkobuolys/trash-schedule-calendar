import json
from datetime import date
from pathlib import Path

import pytest

from trash_calendar.models import ProviderError
from trash_calendar.providers.powerbi_dsr import decode_dsr, epoch_ms_to_date

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_epoch_ms_is_decoded_in_utc_as_a_calendar_date():
    # Power BI serialises date-only values as UTC midnight.
    assert epoch_ms_to_date(1785974400000) == date(2026, 8, 6)
    assert epoch_ms_to_date(1818633600000) == date(2027, 8, 19)


def test_decode_returns_descriptor_names_as_columns():
    names, _ = decode_dsr(load("ekonovus_querydata_packaging.json"))
    assert names == ["inv", "date", "cnt"]


def test_decode_expands_value_dictionary_indices():
    _, rows = decode_dsr(load("ekonovus_querydata_packaging.json"))
    assert all(row[0] == "10-P-000000" for row in rows)


def test_decode_expands_repeat_bitmask_across_all_rows():
    # Only the first row carries every column; the rest set R=5 and supply
    # just the date. Every row must still come out fully populated.
    _, rows = decode_dsr(load("ekonovus_querydata_packaging.json"))
    assert len(rows) == 19
    assert all(len(row) == 3 for row in rows)
    assert all(row[2] == 1 for row in rows)


def test_decode_yields_the_real_packaging_schedule():
    _, rows = decode_dsr(load("ekonovus_querydata_packaging.json"))
    dates = [epoch_ms_to_date(row[1]) for row in rows]
    assert dates[:4] == [
        date(2026, 8, 6),
        date(2026, 8, 27),
        date(2026, 9, 17),
        date(2026, 10, 8),
    ]
    assert dates == sorted(dates), "dates must come back in ascending order"


def test_decode_handles_the_four_column_glass_response():
    names, rows = decode_dsr(load("ekonovus_querydata_glass.json"))
    assert names == ["label", "cadence", "date", "cnt"]
    assert rows[0][0] == "10-S-000000 (Stiklas)"
    assert rows[0][1] == "kas 84 dienas"
    assert [epoch_ms_to_date(r[2]) for r in rows][:2] == [date(2026, 8, 27), date(2026, 11, 19)]


def test_decode_maps_null_bitmask_to_none():
    _, rows = decode_dsr(load("ekonovus_querydata_nullmask.json"))
    assert rows, "nullmask fixture should contain rows"
    assert all(len(row) == 3 for row in rows)


def test_decode_raises_provider_error_on_odata_error():
    response = {
        "results": [
            {
                "result": {
                    "data": {
                        "descriptor": {"Select": [{"Name": "x"}]},
                        "dsr": {
                            "DS": [
                                {
                                    "odata.error": {
                                        "code": "rsDataShapeQueryTranslationError",
                                        "message": {
                                            "value": "not clear how these fields are related"
                                        },
                                    }
                                }
                            ]
                        },
                    }
                }
            }
        ]
    }
    with pytest.raises(ProviderError, match="not clear how these fields are related"):
        decode_dsr(response)


def test_decode_raises_provider_error_when_a_row_precedes_its_column_spec():
    response = {
        "results": [
            {
                "result": {
                    "data": {
                        "descriptor": {"Select": [{"Name": "x"}]},
                        "dsr": {"DS": [{"PH": [{"DM0": [{"C": [1]}]}]}]},
                    }
                }
            }
        ]
    }
    with pytest.raises(ProviderError, match="column spec"):
        decode_dsr(response)


def test_decode_returns_empty_for_an_unknown_container():
    # A filter matching nothing yields an empty DM0, not an error.
    response = {
        "results": [
            {
                "result": {
                    "data": {
                        "descriptor": {"Select": [{"Name": "x"}]},
                        "dsr": {"DS": [{"PH": [{"DM0": []}]}]},
                    }
                }
            }
        ]
    }
    assert decode_dsr(response) == (["x"], [])
