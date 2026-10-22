# trash-schedule-calendar

Waste collection dates in Lithuania are only discoverable by filling in forms on
provider websites, one container at a time, with no notification. This scrapes
them for the containers you configure and syncs the next six months into a
dedicated Google Calendar, as all-day events that remind you **the evening
before** so the containers get pushed out in time.

Runs weekly as a GitHub Action. Nothing to install locally unless you want to.

## Providers

| Provider | Waste types | What it needs | How it is read |
|---|---|---|---|
| `ekonovus` | glass, packaging | container id only | HTTP query against the Power BI report behind [ekonovus.lt](https://www.ekonovus.lt/aptarnavimo-grafikai/) |
| `svara` | mixed municipal | container id **+ address** | Playwright fills the [grafikai.svara.lt](https://grafikai.svara.lt/) address form, then downloads that container's ICS |

**Ekonovus** is queried directly by inventory number, so no address is needed.

**Svara** needs the address because its address form is the only lookup entry
point — the container id is then matched against the results. Its ICS ships a
single recurring event (e.g. every second Wednesday), which is expanded into
individual dates.

## Setup

### 1. Create a dedicated calendar

In Google Calendar, create a new calendar (e.g. `Šiukšlės`). Open its settings
and copy the **Calendar ID**. Use a dedicated calendar: the sync deletes managed
events that are no longer scheduled, and a separate calendar keeps that blast
radius small.

### 2. Create an OAuth client

In [Google Cloud Console](https://console.cloud.google.com/): create a project,
enable the **Google Calendar API**, then create an **OAuth client ID** of type
*Desktop app* and download the client secret JSON.

A user OAuth token is used rather than a service account on purpose. The
Calendar API applies reminder overrides to the *requesting user's* copy of an
event, so a service account would set reminders on its own copy and the
notification would never reach your phone.

### 3. Mint a refresh token

```bash
pip install -e ".[dev]"
python scripts/authorize.py ~/Downloads/client_secret.json
```

This opens a browser once and prints the three values to store as secrets.

### 4. Set repository secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | from step 3 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | from step 3 |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | from step 3 |
| `TRASH_CONFIG_YAML` | your whole `config.yaml`, contents pasted in |

### 5. Configure your containers

Copy `config.example.yaml` and fill in your own values:

```yaml
calendar_id: "your-calendar-id@group.calendar.google.com"
timezone: Europe/Vilnius
horizon_months: 6
reminder_minutes_before: 360 # 18:00 the previous evening

containers:
  - provider: ekonovus
    id: "00-S-00000"

  - provider: svara
    id: "00-MK-000000"
    location:
      region: "Example r. sav."
      subdistrict: "Example sen."
      city: "Example mstl."
      street: "Example g."
      house: "1-1"
```

`config.yaml` is **gitignored**, because it contains your home address — paste it
into the `TRASH_CONFIG_YAML` secret instead. `config.example.yaml` holds only
placeholders. If you don't mind publishing your address, remove `config.yaml`
from `.gitignore` and commit it; the workflow falls back to a committed file when
the secret is unset.

`label` is optional. Failing an explicit label, the provider's own waste type is
used, then the inventory-code convention (`-S-` → stiklas, `-P-` → pakuotės,
`-MK-` → mišrios komunalinės), then the raw id.

### Finding your container ids

They are printed on the container itself, and shown in each provider's own web
UI when you look up your address. Ekonovus ids look like `52-S-00000` (glass) and
`52-P-00000` (packaging); Svara ids look like `52-MK-000000`.

## Local usage

```bash
pip install -e ".[dev]"
python -m playwright install chromium

python -m trash_calendar.cli --dry-run --verbose   # show the diff, change nothing
python -m trash_calendar.cli --verbose             # apply it
```

`--dry-run` works **without** Google credentials — it scrapes and prints the
events it would create, so you can check the schedule before doing any Google
setup.

Flags: `--config PATH`, `--source PROVIDER` (only that provider), `--months N`
(override the horizon), `--force` (allow deleting more than half the managed
events), `--dry-run`, `--verbose`.

Tests:

```bash
pytest              # offline, fixture-driven
pytest -m live      # also hits both providers for real
```

## How the sync behaves

- One all-day event per collection date. Containers collected the same day are
  merged into one event: `🗑️ Išstumti: stiklas + pakuotės`.
- Every event created carries a `managedBy` marker. Each run lists **only**
  marked events, then creates, patches or deletes to match the scrape. Events
  you add to the calendar by hand are never touched.
- Re-running changes nothing if the schedule hasn't changed.

## When something breaks

The job exits non-zero — and GitHub emails you — if a provider returns no dates,
returns an implausible number, changes response shape, or if a run would delete
more than half the managed events.

This matters more than it sounds: the failure mode worth guarding against is a
silent one, where a site changes, nothing is scraped, and the reminders simply
stop.

To debug a provider failure, reproduce it locally — `pytest -m live` writes
`screenshots/` and `traces/` on the spot. CI deliberately uploads neither; see
below.

## A note on privacy

On a public repository, **Actions logs and artifacts are world-readable**, so the
scraper treats them as published output:

- **Container ids are redacted in all log output** (`52-S-***27`). They are not
  opaque tokens — Ekonovus' public API resolves a container id to the street
  address it serves, with no authentication, so a full id in a log discloses the
  address.
- **CI never runs `--verbose`**, because debug logging prints the Calendar API
  URL, which contains the calendar id.
- **No failure artifacts are uploaded**, because Playwright's screenshot of the
  provider's results page shows the address in full.
- `config.yaml` (address) and `.env` (tokens) are gitignored, and
  `tests/test_repo_privacy.py` fails the build if any tracked file contains a
  value from your local config.

The full container id still appears in the calendar event description — that is
your own private calendar, and it is what you need when contacting the operator.

## Adding a provider

Add a module under `trash_calendar/providers/` exposing:

```python
class MyProvider:
    name: ClassVar[str] = "myprovider"
    ConfigModel: ClassVar[type[BaseModel]] = MyContainer  # required config fields

    def fetch(self, container: ContainerConfig, horizon: DateRange) -> list[Collection]: ...
```

Then add one entry to the registry in `trash_calendar/providers/__init__.py`.
`ConfigModel` is what makes a bad config fail at startup naming the missing
field, rather than mid-scrape. Nothing in merging or calendar sync changes.
