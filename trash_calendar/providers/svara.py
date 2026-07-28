"""Svara, driven through its address form because that is its only entry point.

The container id cannot be queried directly. The flow is:

1. Playwright fills the address form and submits it. The app's own request to its
   server function returns a record per container at that address, including a
   ``hashedId`` — plus the waste type and cadence.
2. That hashed id is passed to ``/api/calendar/download/{id}``, a plain REST
   endpoint returning an ICS. (The site's own "Gmail/Outlook" button instead
   opens a captcha-protected *email* dialog, which is why it is not used.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

import requests
from pydantic import BaseModel

from trash_calendar.config import ContainerConfig, Location
from trash_calendar.models import Collection, DateRange, ProviderError
from trash_calendar.providers.ics import parse_ics
from trash_calendar.redact import redact

BASE_URL = "https://grafikai.svara.lt/"
ICS_URL = BASE_URL + "api/calendar/download/{hashed_id}"
ARTIFACTS = Path("screenshots")
TRACES = Path("traces")
NAV_TIMEOUT = 60_000
TIMEOUT = 60

PLACEHOLDERS = {
    "subdistrict": "Pasirinkite seniūniją",
    "city": "Pasirinkite gyvenvietę",
    "street": "Pasirinkite gatvę",
}


class SvaraContainer(BaseModel):
    """Svara needs the address: its only lookup entry point is the address form."""

    id: str
    location: Location


@dataclass(frozen=True)
class Contract:
    """What the site knows about one container at one address."""

    hashed_id: str
    label: str | None = None
    cadence: str | None = None


def decode_seroval(node: Any) -> Any:
    """Decode the seroval envelope the app's server functions reply with.

    Objects arrive as ``{"t":10,"p":{"k":[names],"v":[values]}}``, arrays as
    ``{"t":9,"a":[...]}`` and scalars as ``{"t":N,"s":value}``.
    """
    if isinstance(node, list):
        return [decode_seroval(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "p" in node and isinstance(node["p"], dict) and "k" in node["p"]:
        keys = node["p"]["k"]
        values = node["p"].get("v", [])
        return {key: decode_seroval(value) for key, value in zip(keys, values, strict=False)}
    if "a" in node:
        return [decode_seroval(item) for item in node["a"]]
    if "s" in node:
        return node["s"]
    return node


def find_contract(body: str, container_id: str) -> Contract:
    """Locate the record for one container in a getcontracts response."""
    try:
        decoded = decode_seroval(json.loads(body))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderError(f"could not decode Svara response: {exc}") from exc

    for record in _walk_records(decoded):
        if record.get("inventoryNumber") != container_id:
            continue
        hashed_id = record.get("hashedId")
        if not hashed_id:
            raise ProviderError(f"Svara record for {redact(container_id)!r} has no hashedId")
        return Contract(
            hashed_id=str(hashed_id),
            label=record.get("descriptionFmt") or record.get("description"),
            cadence=record.get("frequency"),
        )

    raise ProviderError(
        f"Svara returned no container matching {redact(container_id)!r} at this address; "
        "check the container number and the address"
    )


def _walk_records(node: Any) -> list[dict[str, Any]]:
    """Collect every mapping that looks like a container record."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "inventoryNumber" in node:
            found.append(node)
        for value in node.values():
            found.extend(_walk_records(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_records(item))
    return found


class Lookup(Protocol):
    def find(self, location: Location, container_id: str) -> Contract: ...


class IcsFetcher(Protocol):
    def fetch(self, hashed_id: str) -> bytes: ...


class PlaywrightLookup:
    """Fills the address form and reads the container record off the response."""

    def find(self, location: Location, container_id: str) -> Contract:
        from playwright.sync_api import sync_playwright

        ARTIFACTS.mkdir(exist_ok=True)
        TRACES.mkdir(exist_ok=True)
        bodies: list[str] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(locale="lt-LT")
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            page.set_default_timeout(NAV_TIMEOUT)

            def capture(response: Any) -> None:
                if "/_serverFn/" not in response.url:
                    return
                try:
                    text = response.text()
                except Exception:  # noqa: BLE001 - a body we cannot read is simply skipped
                    return
                if "inventoryNumber" in text:
                    bodies.append(text)

            page.on("response", capture)

            try:
                page.goto(BASE_URL, wait_until="networkidle")
                page.select_option("select[name=region]", location.region)
                page.wait_for_timeout(1_000)
                for field in ("subdistrict", "city", "street"):
                    self._choose(page, field, getattr(location, field))
                page.get_by_role("textbox").first.fill(location.house)
                page.get_by_role("button", name="Ieškoti").click()
                page.wait_for_timeout(6_000)
            except Exception as exc:
                page.screenshot(path=str(ARTIFACTS / "svara-failure.png"), full_page=True)
                raise ProviderError(
                    f"Svara form lookup failed for {redact(container_id)!r}: {exc}"
                ) from exc
            finally:
                context.tracing.stop(path=str(TRACES / "svara.zip"))
                browser.close()

        for body in bodies:
            if container_id in body:
                return find_contract(body, container_id)
        raise ProviderError(
            f"Svara search returned no record for {redact(container_id)!r}; "
            "the address may be wrong or the site's response shape may have changed"
        )

    @staticmethod
    def _choose(page: Any, field: str, value: str) -> None:
        page.get_by_role("combobox").filter(has_text=PLACEHOLDERS[field]).first.click()
        page.wait_for_timeout(1_000)
        page.get_by_role("option", name=value, exact=True).first.click()
        page.wait_for_timeout(600)


class HttpIcsFetcher:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def fetch(self, hashed_id: str) -> bytes:
        url = ICS_URL.format(hashed_id=hashed_id)
        try:
            response = self.session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Svara ICS download failed for {hashed_id!r}: {exc}") from exc
        return response.content


class SvaraProvider:
    name: ClassVar[str] = "svara"
    ConfigModel: ClassVar[type[BaseModel]] = SvaraContainer

    def __init__(self, lookup: Lookup | None = None, fetcher: IcsFetcher | None = None) -> None:
        self.lookup = lookup or PlaywrightLookup()
        self.fetcher = fetcher or HttpIcsFetcher()

    def fetch(self, container: ContainerConfig, horizon: DateRange) -> list[Collection]:
        if container.location is None:
            raise ProviderError(
                f"svara container {redact(container.id)!r} has no location configured"
            )

        contract = self._run(self.lookup.find, container.location, container.id)
        data = self._run(self.fetcher.fetch, contract.hashed_id)

        return parse_ics(
            data,
            container.id,
            self.name,
            horizon,
            label=container.label or contract.label,
            cadence=contract.cadence,
        )

    @staticmethod
    def _run(function: Any, *args: Any) -> Any:
        try:
            return function(*args)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Svara lookup failed: {exc}") from exc
