"""Shared fixtures.

Live tests exercise the user's own containers, which live in the gitignored
``config.yaml``. They skip when it is absent, so no real address or container id
ever needs to appear in the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trash_calendar.config import Config, ContainerConfig, load_config
from trash_calendar.models import ConfigError

CONFIG_PATH = Path("config.yaml")


@pytest.fixture(scope="session")
def real_config() -> Config:
    if not CONFIG_PATH.exists():
        pytest.skip("live test needs a local config.yaml (see config.example.yaml)")
    try:
        return load_config(CONFIG_PATH)
    except ConfigError as exc:
        pytest.skip(f"local config.yaml is unusable: {exc}")


@pytest.fixture(scope="session")
def real_container(request, real_config: Config) -> ContainerConfig:
    """The first configured container for the provider named via indirect param."""
    provider = request.param
    for container in real_config.containers:
        if container.provider == provider:
            return container
    pytest.skip(f"config.yaml has no {provider} container")
