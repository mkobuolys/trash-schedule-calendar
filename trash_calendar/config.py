"""Load and validate configuration.

Provider-specific requirements are declared by each provider's ``ConfigModel``,
so a bad config fails at startup naming the field rather than mid-scrape.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from trash_calendar.models import ConfigError
from trash_calendar.redact import redact

DEFAULT_CONFIG_PATH = "config.yaml"


class Location(BaseModel):
    region: str
    subdistrict: str
    city: str
    street: str
    house: str


class ContainerConfig(BaseModel):
    provider: str
    id: str
    label: str | None = None
    location: Location | None = None


class Config(BaseModel):
    calendar_id: str
    containers: list[ContainerConfig] = Field(min_length=1)
    timezone: str = "Europe/Vilnius"
    horizon_months: int = Field(default=6, ge=1, le=24)
    reminder_minutes_before: int = Field(default=360, ge=0)


def load_config(path: str | Path | None = None) -> Config:
    resolved = Path(path or os.environ.get("TRASH_CONFIG") or DEFAULT_CONFIG_PATH)
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {resolved}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {resolved} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config file {resolved} must contain a YAML mapping")

    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {resolved}: {exc}") from exc

    for container in config.containers:
        _validate_against_provider(container)
    return config


def _validate_against_provider(container: ContainerConfig) -> None:
    from trash_calendar.providers import get_provider

    try:
        provider = get_provider(container.provider)
    except KeyError as exc:
        raise ConfigError(f"unknown provider {container.provider!r}") from exc

    try:
        provider.ConfigModel.model_validate(container.model_dump())
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        raise ConfigError(
            f"provider {container.provider!r} container {redact(container.id)!r} "
            f"is missing or has invalid required config: {fields}"
        ) from exc
