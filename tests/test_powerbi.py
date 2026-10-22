from __future__ import annotations

from datetime import date

import pytest

from trash_feeds.powerbi import (
    FALLBACK_ENDPOINT,
    Client,
    PowerBIError,
    Query,
    apim_host,
    column,
    decode_page,
    epoch_ms_to_date,
)


def page(dm0, names=("container", "schedule"), restart=None, dicts=None):
    shape = {"N": "DS0", "PH": [{"DM0": dm0}], "ValueDicts": dicts or {}}
    if restart:
        shape["RT"] = restart
    select = [{"Value": f"G{i}", "Name": name} for i, name in enumerate(names)]
    return {
        "results": [
            {"result": {"data": {"descriptor": {"Select": select}, "dsr": {"DS": [shape]}}}}
        ]
    }


SPEC = [{"N": "G0", "T": 1, "DN": "D0"}, {"N": "G1", "T": 4}]


def test_decodes_dictionary_values_repeats_and_nulls():
    response = page(
        [
            {"S": SPEC, "C": [0, 14]},
            {"C": [15], "R": 1},
            {"C": [1], "Ø": 2},
        ],
        dicts={"D0": ["99-S-00001", "99-P-00002"]},
    )

    rows, tokens = decode_page(response)

    assert rows == [
        {"container": "99-S-00001", "schedule": 14},
        {"container": "99-S-00001", "schedule": 15},
        {"container": "99-P-00002", "schedule": None},
    ]
    assert tokens is None


def test_returns_restart_tokens():
    rows, tokens = decode_page(
        page([{"S": SPEC, "C": [0, 1]}], restart=[[None, "1L"]], dicts={"D0": ["x"]})
    )
    assert tokens == [[None, "1L"]]


def test_missing_value_is_an_error():
    with pytest.raises(PowerBIError, match="missing column G1"):
        decode_page(page([{"S": SPEC, "C": [0]}], dicts={"D0": ["x"]}))


def test_odata_error_is_raised():
    response = page([])
    response["results"][0]["result"]["data"]["dsr"]["DS"][0]["odata.error"] = {
        "message": {"value": "bad query"}
    }
    with pytest.raises(PowerBIError, match="bad query"):
        decode_page(response)


def test_unexpected_shape_is_an_error():
    with pytest.raises(PowerBIError, match="unexpected"):
        decode_page({"results": []})


def test_epoch_ms_is_read_in_utc():
    assert epoch_ms_to_date(1793577600000) == date(2026, 11, 2)


def test_apim_host_transform():
    assert (
        apim_host("https://wabi-west-europe-d-primary-redirect.analysis.windows.net/")
        == "https://wabi-west-europe-d-primary-api.analysis.windows.net"
    )


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.bodies = []

    def post(self, url, headers, json, timeout):
        self.bodies.append(json)
        return FakeResponse(self.pages.pop(0))


def test_rows_follow_restart_tokens_across_pages():
    session = FakeSession(
        [
            page([{"S": SPEC, "C": [0, 1]}], restart=[["a", "1L"]], dicts={"D0": ["a"]}),
            page([{"S": SPEC, "C": [0, 2]}], dicts={"D0": ["b"]}),
        ]
    )
    client = Client(session)
    client._endpoint = FALLBACK_ENDPOINT
    query = Query({"d": "Dumpster"}, {"container": column("d", "InventoryNumber")})

    rows = list(client.rows(query))

    assert [row["container"] for row in rows] == ["a", "b"]
    windows = [
        body["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Binding"][
            "DataReduction"
        ]["Primary"]["Window"]
        for body in session.bodies
    ]
    assert "RestartTokens" not in windows[0]
    assert windows[1]["RestartTokens"] == [["a", "1L"]]
