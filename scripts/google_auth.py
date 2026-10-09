#!/usr/bin/env python3
"""Make the Google tokens the bot signs in with: YouTube and Drive.

`pipeline/youtube.py` and the Drive delivery read an authorized-user JSON (a
refresh token), and nothing made one: Google hands you a client secret, not a
token. This runs the one-time consent and writes the token.

    pip install -e '.[youtube]'
    python scripts/google_auth.py youtube client_secret.json state/youtube_token.json
    python scripts/google_auth.py drive   client_secret.json state/drive_token.json

`client_secret.json` is the OAuth client you download from Google Cloud
(APIs & Services > Credentials > Create credentials > OAuth client ID >
Desktop app), in a project with the APIs it needs enabled: the YouTube Data
API v3 and the YouTube Analytics API for `youtube`, the Google Drive API for
`drive`. It prints a link: open it in the browser on the same machine (under
WSL2 the Windows browser works, localhost is forwarded), pick the channel's
Google account, allow it. Then set the line it prints in .env.

Drive takes a token, not a service account, on a personal Google account: a
service account has no storage of its own and Drive refuses its uploads into
a folder you shared with it. Leave GDRIVE_ROOT_FOLDER_ID empty; the bot makes
its own "Dennis" folder, the only kind of folder this token may write into.

Things Google decides, not this script:

* While the consent screen's app is in "Testing", the token stops working
  after seven days and this has to be run again. Publishing the app (it can
  stay unverified for your own account) removes that.
* Until the Cloud project passes YouTube's API audit, every video it uploads
  is locked to private, whatever the bot asks for. Reading retention works
  without the audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 8765


def scopes_for(service: str) -> list[str]:
    if service == "youtube":
        from pipeline.youtube import SCOPES
        return list(SCOPES)
    if service == "drive":
        from pipeline.delivery import GDriveBackend
        return list(GDriveBackend.SCOPES)
    raise SystemExit(f"unknown service {service!r}: youtube or drive")


def make_token(service: str, client_secret: Path, token: Path, *,
               flow_cls=None) -> Path:
    """Run the consent and write the token. `flow_cls` is for the tests."""
    scopes = scopes_for(service)
    if flow_cls is None:
        from google_auth_oauthlib.flow import InstalledAppFlow as flow_cls

    flow = flow_cls.from_client_secrets_file(str(client_secret), scopes)
    # prompt=consent so Google returns a refresh token even for an account
    # that consented before; without one the token dies within the hour.
    creds = flow.run_local_server(port=PORT, open_browser=False,
                                  prompt="consent")
    if not getattr(creds, "refresh_token", None):
        raise SystemExit("Google returned no refresh token; run it again.")
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    try:
        token.chmod(0o600)
    except OSError:
        pass
    return token


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("youtube", "drive"):
        print(__doc__, file=sys.stderr)
        return 2
    service = argv[0]
    client_secret, token = Path(argv[1]).expanduser(), Path(argv[2]).expanduser()
    if not client_secret.exists():
        print(f"no client secret at {client_secret}", file=sys.stderr)
        return 2
    try:
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        print("google-auth-oauthlib is missing: pip install -e '.[youtube]'",
              file=sys.stderr)
        return 2
    out = make_token(service, client_secret, token).resolve()
    lines = (["YOUTUBE_ENABLED=true", f"YOUTUBE_CREDENTIALS={out}"]
             if service == "youtube" else
             ["DELIVERY_BACKEND=gdrive", f"GDRIVE_CREDENTIALS={out}",
              "GDRIVE_ROOT_FOLDER_ID="])
    print(f"wrote {out}\nSet in .env:\n  " + "\n  ".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
