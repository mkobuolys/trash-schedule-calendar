"""Scrape every Ekonovus schedule and write the static subscription site."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from trash_feeds.ekonovus import fetch_containers, fetch_schedules
from trash_feeds.feeds import build_ekonovus, build_svara
from trash_feeds.powerbi import Client, PowerBIError
from trash_feeds.site import ManifestError, previous_feed_ids, write_site

log = logging.getLogger("trash_feeds")

TIMEZONE = ZoneInfo("Europe/Vilnius")
# A full export currently yields ~4,800 schedules and ~510,000 containers.
# Far fewer means the report changed or answered partially; publishing that
# would empty calendars, so the run fails and the live site stays as it is.
MIN_SCHEDULES = 1_000
MIN_CONTAINERS = 100_000


class ImplausibleExport(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--site-url", required=True, help="public base url of the site")
    parser.add_argument("--horizon-days", type=int, default=365)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="skip reading the live manifest (first publish or local preview)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    site_url = args.site_url.rstrip("/")
    stamp = datetime.now(TIMEZONE)
    today = stamp.date()
    end = today + timedelta(days=args.horizon_days)

    try:
        previous = set() if args.fresh else previous_feed_ids(site_url)
        client = Client()
        schedules = fetch_schedules(client)
        containers = fetch_containers(client)
        log.info("exported %d schedules, %d containers", len(schedules), len(containers))
        if len(schedules) < MIN_SCHEDULES or len(containers) < MIN_CONTAINERS:
            raise ImplausibleExport(
                f"only {len(schedules)} schedules and {len(containers)} containers exported; "
                f"expected at least {MIN_SCHEDULES} and {MIN_CONTAINERS}"
            )
    except (PowerBIError, ManifestError, ImplausibleExport) as exc:
        log.error("%s", exc)
        return 1

    feeds, lookup = build_ekonovus(containers, schedules, today, end)
    feeds += build_svara(today, end)
    retired = previous - {feed.id for feed in feeds}
    write_site(args.out, feeds, lookup, retired, site_url, today, stamp)
    log.info(
        "wrote %d feeds (%d retired) and %d container lookups to %s",
        len(feeds),
        len(retired),
        len(lookup),
        args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
