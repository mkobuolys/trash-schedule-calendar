from datetime import date
from pathlib import Path

import pytest

from trash_calendar.config import ContainerConfig, Location
from trash_calendar.models import DateRange, ProviderError
from trash_calendar.providers.svara import (
    Contract,
    SvaraProvider,
    decode_seroval,
    find_contract,
)

FIXTURES = Path(__file__).parent / "fixtures"
ICS = (FIXTURES / "svara_schedule.ics").read_bytes()
CONTRACTS = (FIXTURES / "svara_getcontracts.json").read_text("utf-8")
HORIZON = DateRange(date(2026, 7, 28), date(2027, 1, 28))

LOCATION = Location(
    region="Pavyzdžio r. sav.",
    subdistrict="Pavyzdžio sen.",
    city="Pavyzdžio mstl.",
    street="Pavyzdžio g.",
    house="1-1",
)
CONTAINER = ContainerConfig(provider="svara", id="10-MK-000000", location=LOCATION)


def test_decode_seroval_unwraps_string_and_number_leaves():
    assert decode_seroval({"t": 1, "s": "hello"}) == "hello"
    assert decode_seroval({"t": 0, "s": 0.24}) == 0.24


def test_decode_seroval_zips_object_keys_and_values():
    node = {
        "t": 10,
        "p": {"k": ["a", "b"], "v": [{"t": 1, "s": "x"}, {"t": 0, "s": 2}]},
    }
    assert decode_seroval(node) == {"a": "x", "b": 2}


def test_decode_seroval_expands_arrays():
    node = {"t": 9, "a": [{"t": 1, "s": "x"}, {"t": 1, "s": "y"}]}
    assert decode_seroval(node) == ["x", "y"]


def test_find_contract_extracts_the_hashed_id_from_the_real_response():
    contract = find_contract(CONTRACTS, "10-MK-000000")
    assert contract.hashed_id == "AAAA1111"


def test_find_contract_extracts_label_and_cadence():
    contract = find_contract(CONTRACTS, "10-MK-000000")
    assert contract.label == "Mišrios komunalinės"
    assert contract.cadence == "kas 14 dienų"


def test_find_contract_raises_when_the_container_is_absent():
    with pytest.raises(ProviderError, match="52-XX-999999"):
        find_contract(CONTRACTS, "52-XX-999999")


def test_find_contract_raises_on_unparseable_body():
    with pytest.raises(ProviderError):
        find_contract("<html>not json</html>", "10-MK-000000")


class FakeLookup:
    def __init__(self, contract=None, error=None):
        self.contract = contract
        self.error = error
        self.calls = []

    def find(self, location, container_id):
        self.calls.append((location, container_id))
        if self.error:
            raise self.error
        return self.contract


class FakeFetcher:
    def __init__(self, payload=ICS):
        self.payload = payload
        self.calls = []

    def fetch(self, hashed_id):
        self.calls.append(hashed_id)
        return self.payload


CONTRACT = Contract(hashed_id="AAAA1111", label="Mišrios komunalinės", cadence="kas 14 dienų")


def test_fetch_looks_up_then_downloads_and_parses():
    lookup, fetcher = FakeLookup(CONTRACT), FakeFetcher()
    provider = SvaraProvider(lookup=lookup, fetcher=fetcher)

    collections = provider.fetch(CONTAINER, HORIZON)

    assert lookup.calls == [(LOCATION, "10-MK-000000")]
    assert fetcher.calls == ["AAAA1111"]
    assert len(collections) >= 12
    assert all(c.provider == "svara" for c in collections)
    assert all(c.container_id == "10-MK-000000" for c in collections)
    assert all(HORIZON.contains(c.date) for c in collections)


def test_fetch_uses_the_provider_reported_label_and_cadence():
    provider = SvaraProvider(lookup=FakeLookup(CONTRACT), fetcher=FakeFetcher())
    collections = provider.fetch(CONTAINER, HORIZON)
    assert {c.label for c in collections} == {"Mišrios komunalinės"}
    assert {c.cadence for c in collections} == {"kas 14 dienų"}


def test_configured_label_overrides_the_provider_label():
    container = CONTAINER.model_copy(update={"label": "mišrios"})
    provider = SvaraProvider(lookup=FakeLookup(CONTRACT), fetcher=FakeFetcher())
    assert {c.label for c in provider.fetch(container, HORIZON)} == {"mišrios"}


def test_fetch_requires_a_location():
    provider = SvaraProvider(lookup=FakeLookup(CONTRACT), fetcher=FakeFetcher())
    without = ContainerConfig(provider="svara", id="10-MK-000000")
    with pytest.raises(ProviderError, match="location"):
        provider.fetch(without, HORIZON)


def test_fetch_wraps_lookup_failures_as_provider_error():
    provider = SvaraProvider(
        lookup=FakeLookup(error=RuntimeError("selector missing")), fetcher=FakeFetcher()
    )
    with pytest.raises(ProviderError, match="selector missing"):
        provider.fetch(CONTAINER, HORIZON)


@pytest.mark.live
@pytest.mark.parametrize("real_container", ["svara"], indirect=True)
def test_live_fetch_returns_dates_for_a_configured_container(real_container):
    provider = SvaraProvider()
    collections = provider.fetch(real_container, DateRange(date.today(), date(2027, 6, 1)))
    assert collections
    assert all(c.date >= date.today() for c in collections)
    assert all(c.container_id == real_container.id for c in collections)
