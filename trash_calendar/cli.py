"""Entrypoint: scrape every configured container, then sync the calendar."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date

from trash_calendar.config import Config, load_config
from trash_calendar.gcal import CalendarSync, build_google_client
from trash_calendar.guards import GuardError, check_collections, check_plan
from trash_calendar.merge import merge
from trash_calendar.models import Collection, ConfigError, DateRange, ProviderError
from trash_calendar.providers import get_provider

log = logging.getLogger("trash_calendar")


def build_sync(config: Config) -> CalendarSync:
    client = build_google_client(
        client_id=_require_env("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=_require_env("GOOGLE_OAUTH_CLIENT_SECRET"),
        refresh_token=_require_env("GOOGLE_OAUTH_REFRESH_TOKEN"),
    )
    return CalendarSync(client, config.calendar_id, config.timezone, config.reminder_minutes_before)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"missing required environment variable {name}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="print the diff, change nothing")
    parser.add_argument("--source", default=None, help="only this provider")
    parser.add_argument("--months", type=int, default=None, help="override horizon_months")
    parser.add_argument("--force", action="store_true", help="allow large deletions")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    try:
        config = load_config(args.config)
        horizon = DateRange.from_months(date.today(), args.months or config.horizon_months)
        log.info("horizon: %s .. %s", horizon.start, horizon.end)

        collections: list[Collection] = []
        for container in config.containers:
            if args.source and container.provider != args.source:
                log.info("skipping %s (%s)", container.id, container.provider)
                continue
            provider = get_provider(container.provider)
            found = provider.fetch(container, horizon)
            check_collections(found, container.id)
            log.info("%s (%s): %d dates", container.id, container.provider, len(found))
            collections.extend(found)

        if not collections:
            raise GuardError("no collections gathered from any provider")

        events = merge(collections)
        sync = build_sync(config)
        plan = sync.plan(events, horizon)
        check_plan(plan, force=args.force)

        log.info(
            "plan: %d create, %d patch, %d delete, %d unchanged",
            len(plan.to_create),
            len(plan.to_patch),
            len(plan.to_delete),
            len(plan.unchanged),
        )
        for body in plan.to_create:
            log.info("  + %s %s", body["start"]["date"], body["summary"])
        for _, body in plan.to_patch:
            log.info("  ~ %s %s", body["start"]["date"], body["summary"])
        for _, current in plan.to_delete:
            log.info("  - %s %s", current.get("start", {}).get("date"), current.get("summary"))

        sync.apply(plan, dry_run=args.dry_run)
        if args.dry_run:
            log.info("dry run: nothing was changed")
        return 0

    except (ConfigError, ProviderError, GuardError) as exc:
        log.error("FAILED: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
