import json
from datetime import date
from pathlib import Path

import pytest

from trash_calendar.config import ContainerConfig
from trash_calendar.models import DateRange, ProviderError
from trash_calendar.providers.ekonovus import (
    SCHEDULES_PAGE,
    EkonovusProvider,
    HttpTransport,
    apim_host,
    build_query,
    parse_embed_resource_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_apim_transform_strips_redirect_and_appends_api():
    assert (
        apim_host("https://wabi-west-europe-d-primary-redirect.analysis.windows.net/")
        == "https://wabi-west-europe-d-primary-api.analysis.windows.net"
    )


def test_apim_transform_also_strips_global_prefix():
    assert (
        apim_host("https://global-wabi-north-europe-h-primary-redirect.analysis.windows.net/")
        == "https://wabi-north-europe-h-primary-api.analysis.windows.net"
    )


def test_embed_resource_key_is_base64_decoded_from_the_r_parameter():
    url = (
        "https://app.powerbi.com/view?r=eyJrIjoiZDg2ZGMzZDQtZTkxNS00NDYwLWIxMmUtYzkyNW"
        "QzYWU2Yzc1IiwidCI6IjAwYTZmZGY2LTQ5YzgtNDZhOC1iZGUwLWQzZjhkOTQ4MmYxMSIsImMiOjl9"
    )
    assert parse_embed_resource_key(url) == "d86dc3d4-e915-4460-b12e-c925d3ae6c75"


def test_query_filters_the_bare_dumpster_inventory_number_exactly():
    query = build_query("10-S-000000")
    body = json.dumps(query)
    assert "'10-S-000000'" in body
    where = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]["Query"][
        "Where"
    ]
    inventory_filter = where[0]["Condition"]["In"]["Expressions"][0]["Column"]
    assert inventory_filter["Property"] == "InventoryNumber"


def test_query_restricts_to_future_dates():
    query = build_query("10-S-000000")
    body = json.dumps(query)
    assert "Future" in body


def test_query_selects_the_label_from_wasteobject_not_dumpster():
    select = build_query("10-S-000000")["queries"][0]["Query"]["Commands"][0][
        "SemanticQueryDataShapeCommand"
    ]["Query"]["Select"]
    assert select[0]["Column"]["Property"] == "Inventorinis nr."


def test_query_ends_with_an_aggregate_to_constrain_the_join():
    # Without a trailing aggregate the API answers InvalidUnconstrainedJoin.
    select = build_query("10-S-000000")["queries"][0]["Query"]["Commands"][0][
        "SemanticQueryDataShapeCommand"
    ]["Query"]["Select"]
    assert "Aggregation" in select[-1]


def test_query_never_uses_the_truncated_datos_measure():
    # Datos is capped at 12 dates and includes the past.
    assert "Datos" not in json.dumps(build_query("10-S-000000"))


class FakeTransport:
    """Returns a canned querydata response and records the request."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def query(self, body):
        self.calls.append(body)
        return self.response


def test_fetch_returns_collections_within_the_horizon():
    response = json.loads((FIXTURES / "ekonovus_querydata_glass.json").read_text("utf-8"))
    provider = EkonovusProvider(transport=FakeTransport(response))
    container = ContainerConfig(provider="ekonovus", id="10-S-000000")
    horizon = DateRange(date(2026, 7, 28), date(2027, 1, 28))

    collections = provider.fetch(container, horizon)

    assert [c.date for c in collections] == [date(2026, 8, 27), date(2026, 11, 19)]
    assert {c.container_id for c in collections} == {"10-S-000000"}
    assert {c.provider for c in collections} == {"ekonovus"}
    assert {c.label for c in collections} == {"Stiklas"}
    assert {c.cadence for c in collections} == {"kas 84 dienas"}


def test_fetch_excludes_dates_beyond_the_horizon():
    # This fixture was captured with build_query itself, so it has all four columns.
    response = json.loads((FIXTURES / "ekonovus_querydata_packaging_full.json").read_text("utf-8"))
    provider = EkonovusProvider(transport=FakeTransport(response))
    container = ContainerConfig(provider="ekonovus", id="10-P-000000")
    horizon = DateRange(date(2026, 7, 28), date(2026, 9, 30))

    dates = [c.date for c in provider.fetch(container, horizon)]

    assert dates == [date(2026, 8, 6), date(2026, 8, 27), date(2026, 9, 17)]


def test_fetch_reports_a_missing_column_rather_than_raising_keyerror():
    # If the report's model changes shape, the failure must name the column.
    response = json.loads((FIXTURES / "ekonovus_querydata_packaging.json").read_text("utf-8"))
    provider = EkonovusProvider(transport=FakeTransport(response))
    container = ContainerConfig(provider="ekonovus", id="10-P-000000")
    with pytest.raises(ProviderError, match="label"):
        provider.fetch(container, DateRange(date(2026, 7, 28), date(2027, 1, 28)))


def test_fetch_raises_when_the_container_is_unknown_to_this_provider():
    empty = {
        "results": [
            {
                "result": {
                    "data": {
                        "descriptor": {
                            "Select": [
                                {"Name": "label"},
                                {"Name": "cadence"},
                                {"Name": "date"},
                                {"Name": "cnt"},
                            ]
                        },
                        "dsr": {"DS": [{"PH": [{"DM0": []}]}]},
                    }
                }
            }
        ]
    }
    provider = EkonovusProvider(transport=FakeTransport(empty))
    container = ContainerConfig(provider="ekonovus", id="10-MK-000000")
    # The error must carry the redacted id, never the full one.
    with pytest.raises(ProviderError, match=r"10-MK-\*\*\*00"):
        provider.fetch(container, DateRange(date(2026, 7, 28), date(2027, 1, 28)))


def test_http_transport_does_not_identify_as_python_requests():
    # ekonovus.lt answers 403 to the python-requests User-Agent.
    assert "python-requests" not in HttpTransport().session.headers["User-Agent"]


@pytest.mark.live
def test_live_schedules_page_serves_the_embed_to_the_transport_session():
    page = HttpTransport().session.get(SCHEDULES_PAGE, timeout=60)
    assert page.status_code == 200
    assert "app.powerbi.com/view" in page.text


@pytest.mark.live
@pytest.mark.parametrize("real_container", ["ekonovus"], indirect=True)
def test_live_fetch_returns_future_dates_for_a_configured_container(real_container):
    provider = EkonovusProvider()
    collections = provider.fetch(real_container, DateRange(date.today(), date(2028, 1, 1)))
    assert collections
    assert all(c.date >= date.today() for c in collections)
    assert all(c.container_id == real_container.id for c in collections)
