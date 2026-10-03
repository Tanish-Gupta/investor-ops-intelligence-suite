"""Google credentials for the MCP server (ported from M3 `google_auth.py`).

* OAuth user (personal/demo account): run once
      uv run python -m pillar_c_mcp.google.auth
  to open the consent screen and write `GOOGLE_TOKEN_PATH` (secrets/token.json).
* Service account (Workspace): `GOOGLE_SERVICE_ACCOUNT_FILE` (+ domain-wide delegation).

Scopes are the minimum the five tools need; `gmail.compose` allows drafts and the server simply
has no tool that sends. Credentials live in `secrets/` and are never committed or logged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GoogleAuthError(RuntimeError):
    pass


def load_credentials(
    *,
    token_file: Path | str | None,
    service_account_file: Path | str | None = None,
    delegated_user: str | None = None,
) -> Any:
    """Return google-auth credentials; refreshes an expired OAuth token and saves it back."""
    if service_account_file:
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            str(service_account_file), scopes=SCOPES
        )
        return creds.with_subject(delegated_user) if delegated_user else creds

    if not token_file or not Path(token_file).exists():
        raise GoogleAuthError(
            "No Google credentials. Run `uv run python -m pillar_c_mcp.google.auth` (OAuth) "
            "or set GOOGLE_SERVICE_ACCOUNT_FILE."
        )
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            Path(token_file).write_text(creds.to_json())
        else:
            raise GoogleAuthError(f"Google token in {token_file} is invalid; re-run consent")
    return creds


def build_services(creds: Any) -> tuple[Any, Any, Any]:
    """(calendar, docs, gmail) discovery clients; `cache_discovery=False` avoids file caches."""
    from googleapiclient.discovery import build

    return (
        build("calendar", "v3", credentials=creds, cache_discovery=False),
        build("docs", "v1", credentials=creds, cache_discovery=False),
        build("gmail", "v1", credentials=creds, cache_discovery=False),
    )


def run_consent_flow(client_secrets: Path | str, token_file: Path | str) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(port=0)
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    Path(token_file).write_text(creds.to_json())


def main() -> None:
    from config.settings import get_settings

    s = get_settings()
    if not Path(s.google_client_secrets_path).exists():
        raise SystemExit(
            "Save the OAuth client JSON (Google Cloud Console → Credentials → Desktop app) to "
            f"{s.google_client_secrets_path} first."
        )
    run_consent_flow(s.google_client_secrets_path, s.google_token_path)
    print(f"Saved Google token to {s.google_token_path}")


if __name__ == "__main__":
    main()
