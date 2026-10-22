"""Bulk reads from the Power BI publish-to-web report behind ekonovus.lt.

The public querydata API needs no authentication. Results arrive in Power BI's
compressed DSR encoding and are paged with restart tokens.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import requests

SCHEDULES_PAGE = "https://www.ekonovus.lt/aptarnavimo-grafikai/"
TIMEOUT = 120
PAGE_SIZE = 30_000
ATTEMPTS = 3
# ekonovus.lt answers 403 to the python-requests User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class PowerBIError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    host: str
    resource_key: str
    model_id: int
    dataset_id: str


# Verified 2026-10-22. Used when runtime resolution fails.
FALLBACK_ENDPOINT = Endpoint(
    host="https://wabi-west-europe-d-primary-api.analysis.windows.net",
    resource_key="d86dc3d4-e915-4460-b12e-c925d3ae6c75",
    model_id=1026609,
    dataset_id="90015897-045e-4f68-8f83-c40d1fc3bfc2",
)


def column(source: str, prop: str) -> dict[str, Any]:
    return {"Column": {"Expression": {"SourceRef": {"Source": source}}, "Property": prop}}


def count(source: str, prop: str) -> dict[str, Any]:
    return {"Aggregation": {"Expression": column(source, prop), "Function": 2}}


def equals(source: str, prop: str, literal: str) -> dict[str, Any]:
    return {
        "Condition": {
            "In": {
                "Expressions": [column(source, prop)],
                "Values": [[{"Literal": {"Value": literal}}]],
            }
        }
    }


def not_null(source: str, prop: str) -> dict[str, Any]:
    comparison = {
        "ComparisonKind": 0,
        "Left": column(source, prop),
        "Right": {"Literal": {"Value": "null"}},
    }
    return {"Condition": {"Not": {"Expression": {"Comparison": comparison}}}}


@dataclass(frozen=True)
class Query:
    """A grouped select. ``entities`` maps alias to entity name."""

    entities: dict[str, str]
    select: dict[str, dict[str, Any]]
    where: list[dict[str, Any]] = field(default_factory=list)

    def body(self, endpoint: Endpoint, restart_tokens: Any = None) -> dict[str, Any]:
        window: dict[str, Any] = {"Count": PAGE_SIZE}
        if restart_tokens:
            window["RestartTokens"] = restart_tokens
        command = {
            "SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [
                        {"Name": alias, "Entity": entity, "Type": 0}
                        for alias, entity in self.entities.items()
                    ],
                    "Select": [dict(expr, Name=name) for name, expr in self.select.items()],
                    "Where": self.where,
                },
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": list(range(len(self.select)))}]},
                    "DataReduction": {"DataVolume": 4, "Primary": {"Window": window}},
                    "Version": 1,
                },
            }
        }
        return {
            "version": "1.0.0",
            "queries": [
                {
                    "Query": {"Commands": [command]},
                    "QueryId": "",
                    "ApplicationContext": {"DatasetId": endpoint.dataset_id},
                }
            ],
            "cancelQueries": [],
            "modelId": endpoint.model_id,
        }


def epoch_ms_to_date(value: int) -> date:
    """Power BI date-only values are UTC midnight, so they must be read in UTC."""
    return datetime.fromtimestamp(value / 1000, tz=UTC).date()


def decode_page(response: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    """Return (rows keyed by select name, restart tokens or None) for one page.

    Each row carries a bitmask of columns repeating the previous row (``R``) and
    of null columns (``Ø``); only the remaining values are present in ``C``,
    with strings replaced by indexes into the page's value dictionaries.
    """
    try:
        data = response["results"][0]["result"]["data"]
        shape = data["dsr"]["DS"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PowerBIError(f"unexpected querydata response shape: {exc!r}") from exc

    if "odata.error" in shape:
        raise PowerBIError(shape["odata.error"]["message"]["value"])

    names = {entry["Value"]: entry["Name"] for entry in data["descriptor"]["Select"]}
    dictionaries = shape.get("ValueDicts", {})

    rows: list[dict[str, Any]] = []
    spec: list[dict[str, Any]] | None = None
    previous: list[Any] = []

    for item in shape.get("PH", [{}])[0].get("DM0", []):
        if "S" in item:
            spec = item["S"]
        if spec is None:
            raise PowerBIError("DSR row appeared before its column spec")

        repeats = item.get("R", 0)
        nulls = item.get("Ø", 0)
        present = iter(item.get("C", []))
        values: list[Any] = []

        for index, col in enumerate(spec):
            if repeats >> index & 1:
                values.append(previous[index])
            elif nulls >> index & 1:
                values.append(None)
            else:
                try:
                    value = next(present)
                except StopIteration as exc:
                    raise PowerBIError(f"DSR row is missing column {col.get('N')}") from exc
                dictionary = col.get("DN")
                if dictionary and isinstance(value, int):
                    value = dictionaries[dictionary][value]
                values.append(value)

        previous = values
        rows.append({names[col["N"]]: value for col, value in zip(spec, values, strict=True)})

    return rows, shape.get("RT")


def apim_host(cluster_uri: str) -> str:
    """Apply Power BI's documented APIM hostname transform."""
    match = re.match(r"(https?)://([^/]+)", cluster_uri)
    if not match:
        raise PowerBIError(f"unrecognised cluster uri: {cluster_uri}")
    scheme, hostname = match.groups()
    labels = hostname.split(".")
    labels[0] = labels[0].replace("-redirect", "").replace("global-", "") + "-api"
    return f"{scheme}://{'.'.join(labels)}"


def parse_embed_resource_key(embed_url: str) -> str:
    match = re.search(r"[?&]r=([A-Za-z0-9_\-=]+)", embed_url)
    if not match:
        raise PowerBIError(f"no ?r= parameter in embed url: {embed_url}")
    token = match.group(1)
    try:
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (ValueError, binascii.Error) as exc:
        raise PowerBIError(f"could not decode embed token: {exc}") from exc
    if not payload.get("k"):
        raise PowerBIError("embed token has no 'k' resource key")
    return payload["k"]


class Client:
    def __init__(self, session: requests.Session | None = None) -> None:
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
        self.session = session
        self._endpoint: Endpoint | None = None

    @property
    def endpoint(self) -> Endpoint:
        if self._endpoint is None:
            self._endpoint = self._resolve()
        return self._endpoint

    def rows(self, query: Query) -> Iterator[dict[str, Any]]:
        tokens = None
        while True:
            page, tokens = decode_page(self._post(query.body(self.endpoint, tokens)))
            yield from page
            if not tokens:
                return

    def _resolve(self) -> Endpoint:
        try:
            page = self.session.get(SCHEDULES_PAGE, timeout=TIMEOUT).text
            embed = re.search(r"https://app\.powerbi\.com/view\?r=[A-Za-z0-9_\-=]+", page)
            if not embed:
                raise PowerBIError("no Power BI embed url on the Ekonovus schedules page")
            resource_key = parse_embed_resource_key(embed.group(0))

            view = self.session.get(embed.group(0), timeout=TIMEOUT).text
            cluster = re.search(r"resolvedClusterUri\s*=\s*'([^']+)'", view)
            host = apim_host(cluster.group(1)) if cluster else FALLBACK_ENDPOINT.host

            response = self.session.get(
                host + "/public/reports/modelsAndExploration?preferReadOnlySession=true",
                headers=self._headers(resource_key),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            model = response.json()["models"][0]
            return Endpoint(host, resource_key, int(model["id"]), model["dbName"])
        except (requests.RequestException, KeyError, IndexError, ValueError, PowerBIError):
            return FALLBACK_ENDPOINT

    def _headers(self, resource_key: str) -> dict[str, str]:
        # ActivityId and RequestId are mandatory; without them the API returns 403.
        return {
            "X-PowerBI-ResourceKey": resource_key,
            "ActivityId": str(uuid.uuid4()),
            "RequestId": str(uuid.uuid4()),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://app.powerbi.com",
            "Referer": "https://app.powerbi.com/",
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        url = self.endpoint.host + "/public/reports/querydata?synchronous=true"
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self.session.post(
                    url,
                    headers=self._headers(self.endpoint.resource_key),
                    json=body,
                    timeout=TIMEOUT,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == ATTEMPTS:
                    raise PowerBIError(f"querydata request failed: {exc}") from exc
                time.sleep(5 * attempt)
        raise AssertionError("unreachable")
