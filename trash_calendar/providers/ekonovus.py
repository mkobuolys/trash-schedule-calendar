"""Ekonovus, read through its embedded Power BI publish-to-web report.

The public querydata API is callable over plain HTTP with no authentication.
Lookup is by container inventory number alone; no address is required.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import requests
from pydantic import BaseModel

from trash_calendar.config import ContainerConfig
from trash_calendar.models import Collection, DateRange, ProviderError
from trash_calendar.providers.powerbi_dsr import decode_dsr, epoch_ms_to_date
from trash_calendar.redact import redact

SCHEDULES_PAGE = "https://www.ekonovus.lt/aptarnavimo-grafikai/"

# Verified 2026-07-28. Used when runtime resolution fails.
FALLBACK_HOST = "https://wabi-west-europe-d-primary-api.analysis.windows.net"
FALLBACK_RESOURCE_KEY = "d86dc3d4-e915-4460-b12e-c925d3ae6c75"
FALLBACK_MODEL_ID = 1026609
FALLBACK_DATASET_ID = "90015897-045e-4f68-8f83-c40d1fc3bfc2"

TIMEOUT = 60


class EkonovusContainer(BaseModel):
    """Ekonovus needs nothing but the inventory number."""

    id: str


@dataclass(frozen=True)
class Endpoint:
    host: str
    resource_key: str
    model_id: int
    dataset_id: str


def apim_host(cluster_uri: str) -> str:
    """Apply Power BI's documented APIM hostname transform."""
    match = re.match(r"(https?)://([^/]+)", cluster_uri)
    if not match:
        raise ProviderError(f"unrecognised cluster uri: {cluster_uri}")
    scheme, hostname = match.groups()
    labels = hostname.split(".")
    labels[0] = labels[0].replace("-redirect", "").replace("global-", "") + "-api"
    return f"{scheme}://{'.'.join(labels)}"


def parse_embed_resource_key(embed_url: str) -> str:
    match = re.search(r"[?&]r=([A-Za-z0-9_\-=]+)", embed_url)
    if not match:
        raise ProviderError(f"no ?r= parameter in embed url: {embed_url}")
    token = match.group(1)
    padded = token + "=" * (-len(token) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error) as exc:
        raise ProviderError(f"could not decode embed token: {exc}") from exc
    key = payload.get("k")
    if not key:
        raise ProviderError("embed token has no 'k' resource key")
    return key


def _column(source: str, prop: str) -> dict[str, Any]:
    return {"Column": {"Expression": {"SourceRef": {"Source": source}}, "Property": prop}}


def build_query(
    container_id: str,
    dataset_id: str = FALLBACK_DATASET_ID,
    model_id: int = FALLBACK_MODEL_ID,
) -> dict[str, Any]:
    """Build the verified querydata body for one container.

    Two non-obvious requirements, both enforced by tests:
      * the trailing Count aggregate is what constrains the join across
        Dumpster/WasteObject/Schedule/ScheduleDates;
      * the exact-match filter targets Dumpster.InventoryNumber, because
        WasteObject."Inventorinis nr." appends the waste type in parentheses.
    """
    select = [
        dict(_column("w", "Inventorinis nr."), Name="label"),
        dict(_column("sc", "Description"), Name="cadence"),
        dict(_column("s", "Date"), Name="date"),
        {
            "Aggregation": {"Expression": _column("s", "Id"), "Function": 2},
            "Name": "cnt",
        },
    ]
    command = {
        "SemanticQueryDataShapeCommand": {
            "Query": {
                "Version": 2,
                "From": [
                    {"Name": "d", "Entity": "Dumpster", "Type": 0},
                    {"Name": "w", "Entity": "WasteObject", "Type": 0},
                    {"Name": "sc", "Entity": "Schedule", "Type": 0},
                    {"Name": "s", "Entity": "ScheduleDates", "Type": 0},
                ],
                "Select": select,
                "Where": [
                    {
                        "Condition": {
                            "In": {
                                "Expressions": [_column("d", "InventoryNumber")],
                                "Values": [[{"Literal": {"Value": f"'{container_id}'"}}]],
                            }
                        }
                    },
                    {
                        "Condition": {
                            "In": {
                                "Expressions": [_column("s", "Future")],
                                "Values": [[{"Literal": {"Value": "'true'"}}]],
                            }
                        }
                    },
                ],
            },
            "Binding": {
                "Primary": {"Groupings": [{"Projections": [0, 1, 2, 3]}]},
                "DataReduction": {"DataVolume": 3, "Primary": {"Window": {"Count": 1000}}},
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
                "ApplicationContext": {"DatasetId": dataset_id},
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
    }


class Transport(Protocol):
    def query(self, body: dict[str, Any]) -> dict[str, Any]: ...


class HttpTransport:
    """Resolves the Power BI endpoint, then posts querydata requests."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._endpoint: Endpoint | None = None

    def endpoint(self) -> Endpoint:
        if self._endpoint is None:
            self._endpoint = self._resolve()
        return self._endpoint

    def _resolve(self) -> Endpoint:
        try:
            page = self.session.get(SCHEDULES_PAGE, timeout=TIMEOUT).text
            embed = re.search(r"https://app\.powerbi\.com/view\?r=[A-Za-z0-9_\-=]+", page)
            if not embed:
                raise ProviderError("no Power BI embed url on the Ekonovus schedules page")
            embed_url = embed.group(0)
            resource_key = parse_embed_resource_key(embed_url)

            view = self.session.get(embed_url, timeout=TIMEOUT).text
            cluster = re.search(r"resolvedClusterUri\s*=\s*'([^']+)'", view)
            host = apim_host(cluster.group(1)) if cluster else FALLBACK_HOST

            models = self._get(
                host,
                resource_key,
                "/public/reports/modelsAndExploration?preferReadOnlySession=true",
            )
            model = models["models"][0]
            return Endpoint(host, resource_key, int(model["id"]), model["dbName"])
        except (requests.RequestException, KeyError, IndexError, ValueError, ProviderError):
            return Endpoint(
                FALLBACK_HOST, FALLBACK_RESOURCE_KEY, FALLBACK_MODEL_ID, FALLBACK_DATASET_ID
            )

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

    def _get(self, host: str, resource_key: str, path: str) -> dict[str, Any]:
        response = self.session.get(
            host + path, headers=self._headers(resource_key), timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def query(self, body: dict[str, Any]) -> dict[str, Any]:
        endpoint = self.endpoint()
        try:
            response = self.session.post(
                endpoint.host + "/public/reports/querydata?synchronous=true",
                headers=self._headers(endpoint.resource_key),
                json=body,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Ekonovus querydata request failed: {exc}") from exc


class EkonovusProvider:
    name: ClassVar[str] = "ekonovus"
    ConfigModel: ClassVar[type[BaseModel]] = EkonovusContainer

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or HttpTransport()

    def fetch(self, container: ContainerConfig, horizon: DateRange) -> list[Collection]:
        response = self.transport.query(build_query(container.id))
        names, rows = decode_dsr(response)
        index = {name: position for position, name in enumerate(names)}

        if not rows:
            raise ProviderError(
                f"Ekonovus returned no schedule for container {redact(container.id)!r}; "
                "check the inventory number or whether this container belongs to "
                "another provider"
            )

        missing = [column for column in ("label", "cadence", "date") if column not in index]
        if missing:
            raise ProviderError(
                f"Ekonovus response is missing expected column(s) {', '.join(missing)}; "
                f"got {names}. The report's model may have changed."
            )

        collections: list[Collection] = []
        for row in rows:
            when = epoch_ms_to_date(row[index["date"]])
            if not horizon.contains(when):
                continue
            collections.append(
                Collection(
                    date=when,
                    container_id=container.id,
                    provider=self.name,
                    label=_waste_type(row[index["label"]]),
                    cadence=row[index["cadence"]],
                )
            )
        return sorted(collections, key=lambda c: c.date)


def _waste_type(label: str | None) -> str | None:
    """Extract 'Stiklas' from '00-S-00000 (Stiklas)'."""
    if not label:
        return None
    match = re.search(r"\(([^)]+)\)\s*$", label)
    return match.group(1) if match else None
