"""One-time OAuth consent. Prints the refresh token for GitHub Secrets.

Usage:
    python scripts/authorize.py path/to/client_secret.json

Create the OAuth client in Google Cloud Console as an installed/desktop app
with the Calendar API enabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Runnable straight from a checkout, without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from trash_calendar.gcal import SCOPES  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent")
    if not credentials.refresh_token:
        print(
            "\nNo refresh token was returned. Revoke the app's access at "
            "https://myaccount.google.com/permissions and run this again.",
            file=sys.stderr,
        )
        return 1
    print("\nStore these as GitHub secrets:")
    print(f"GOOGLE_OAUTH_CLIENT_ID={credentials.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={credentials.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
