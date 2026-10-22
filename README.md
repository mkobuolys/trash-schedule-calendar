# trash-schedule-calendar

In Lithuania, waste collection dates can only be found by filling in forms on
the provider's website, one container at a time, with no notifications. This
project puts them in your calendar instead. It's built for people who have
never heard of GitHub: you open a web page, type the number printed on your
bin, and add the schedule to Google, Apple or Outlook Calendar with one click.
There's no account to create and nothing to install. Calendar apps re-fetch
subscribed links on their own, and that is what keeps the schedule in sync.

Everything runs on GitHub, free:

```
GitHub Action (daily)                       GitHub Pages (static)
 ├─ export every Ekonovus schedule  ───►    ├─ index.html, app.js, logic.js
 ├─ one .ics per (waste type, schedule set) ├─ feeds/<id>.ics        (~3,100)
 ├─ one .ics per Svara recurrence           ├─ feeds/svara-*.ics     (70)
 └─ container → feed lookup                 ├─ lookup/<xx>.json      (256 shards)
                                            └─ manifest.json
```

## How it works

**Ekonovus.** The Power BI report behind ekonovus.lt is queried in bulk: every
future collection date of every schedule (~4,800), and every container's
schedules (~515,000 containers). Containers with the same waste type and the
same set of schedules share one feed, so the ~512,000 active containers collapse
into ~3,100 feeds. The page finds a container's feed in `lookup/<xx>.json`,
where `xx` is the first byte of the SHA-256 of the normalized container number.
That lookup runs in the browser; the number is never sent anywhere.

**Svara.** Since October 2026, grafikai.svara.lt has put its form and every
download endpoint behind a Cloudflare Turnstile "confirm you are human" check,
which no unattended client can pass. Its schedules are a single
fixed recurrence anyway, so the person enters their next collection date and
how often it repeats. Every weekly recurrence that can be described that way
(7 weekdays × every 1–4 weeks × which week of the cycle) is only 70 feeds, all
pre-generated. The page computes which one from the date.

**Reminders.** Each event carries an alarm at 18:00 the evening before. Apple
Calendar honours it. Google Calendar and Outlook ignore alarms in subscribed
calendars, so the page tells Google users to set the calendar's all-day
notification once.

**Feed links never break.** A feed's id is a hash of its waste type and schedule
set. If Ekonovus moves containers to another schedule, their old feed would
disappear and subscribed calendars would quietly stop updating. To prevent
that, each build reads the live `manifest.json` and republishes every feed id
that no longer exists as a notice feed ("Šiukšlių grafikas pasikeitė…") telling
subscribers to add their calendar again.

**Failing safely.** The build fails, and the deploy is skipped, when the export
returns far fewer schedules or containers than expected, or when the live
manifest cannot be read. The site already published stays up with the previous
day's data, and GitHub emails the repository owner.

## Privacy

A feed link contains neither a container number nor an address, only the id of
a schedule shared by many households. The site publishes the container →
schedule mapping, which Ekonovus already publishes; it publishes no addresses.

## One-time setup

1. Settings → Pages → **Source: GitHub Actions**.
2. Merge to `main` (or run the workflow by hand). The page is served at
   `https://<owner>.github.io/<repo>/`.

The workflow runs daily at 03:00 UTC. Its `keepalive` job re-enables the
workflow through the API, because GitHub disables scheduled workflows after 60
days without repository activity.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/pytest                         # offline
.venv/bin/pytest -m live                 # also exports from the real report
node --test tests/js/logic.test.mjs      # page logic

.venv/bin/python -m trash_feeds.cli --out /tmp/site --site-url http://localhost:8000 --fresh
python -m http.server 8000 --directory /tmp/site
```

`--fresh` skips reading the live manifest. A full export takes about a minute
and writes ~90 MB.

`normalizeId`, `shardOf` and `svaraFeedId` in `site/logic.js` must agree with
their Python counterparts in `trash_feeds/feeds.py`. Both test suites assert the
same vectors.
