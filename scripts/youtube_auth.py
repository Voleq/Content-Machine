#!/usr/bin/env python3
"""Mint the YouTube credentials `/upload` reads, with the scopes it needs.

`YOUTUBE_CREDENTIALS` is an authorized-user JSON (a refresh token), and
nothing in the repo made one: an operator had to assemble it by hand, and a
token minted with only `youtube.upload` uploads fine and then answers 403 to
the caption track, the pinned comment and `/correct`'s description edit —
each of which needs `youtube.force-ssl`. This asks for exactly the scopes
`pipeline.youtube.SCOPES` declares.

    1. Google Cloud console: enable "YouTube Data API v3" and
       "YouTube Analytics API"; create an OAuth client of type "Desktop app";
       download its JSON.
    2. python scripts/youtube_auth.py client_secret.json --out state/youtube.json
       (a browser opens; sign in as the channel's account)
    3. YOUTUBE_CREDENTIALS=state/youtube.json in .env

An OAuth app left in "Testing" issues refresh tokens that expire after seven
days. Publish the app (no verification is needed for your own channel) or
re-run this weekly.

`--drive` mints `GDRIVE_CREDENTIALS` for DELIVERY_BACKEND=gdrive the same way,
with the one scope the Drive backend asks for (`drive.file`: only the files
and folders this app makes), from the same client JSON once "Google Drive
API" is enabled in the same project:

    python scripts/youtube_auth.py client_secret.json --drive
    GDRIVE_CREDENTIALS=state/gdrive.json in .env

A personal Google account has no Shared Drive, and a service account has no
storage of its own, so this is the way in for a channel on a gmail account.

Needs `pip install '.[youtube]'`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("client_secret", type=Path,
                    help="the OAuth client JSON downloaded from the console")
    ap.add_argument("--out", type=Path, default=None,
                    help="where to write the authorized-user JSON (default "
                         "state/youtube.json, or state/gdrive.json with --drive)")
    ap.add_argument("--drive", action="store_true",
                    help="mint GDRIVE_CREDENTIALS (the drive.file scope) "
                         "instead of YOUTUBE_CREDENTIALS")
    ap.add_argument("--no-browser", action="store_true",
                    help="print the URL instead of opening a browser. The "
                         "sign-in still returns to this machine's localhost: "
                         "on a headless box pick a --port and forward it "
                         "(ssh -L PORT:localhost:PORT box), then open the "
                         "URL on your own computer. Under WSL, Windows "
                         "reaches it directly")
    ap.add_argument("--port", type=int, default=0,
                    help="the localhost port the sign-in returns to "
                         "(default: any free one)")
    args = ap.parse_args(argv)
    if args.drive:
        from pipeline.delivery import GDriveBackend
        scopes, setting = list(GDriveBackend.SCOPES), "GDRIVE_CREDENTIALS"
    else:
        from pipeline.youtube import SCOPES
        scopes, setting = list(SCOPES), "YOUTUBE_CREDENTIALS"
    if args.out is None:
        args.out = ROOT / "state" / ("gdrive.json" if args.drive else "youtube.json")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("google-auth-oauthlib is not installed: pip install '.[youtube]'",
              file=sys.stderr)
        return 2
    if not args.client_secret.exists():
        print(f"no client secret at {args.client_secret}", file=sys.stderr)
        return 2

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret),
                                                     scopes)
    creds = flow.run_local_server(port=args.port,
                                  open_browser=not args.no_browser,
                                  prompt="consent", access_type="offline")
    if not creds.refresh_token:
        print("Google returned no refresh token — revoke the app's access at "
              "myaccount.google.com/permissions and run this again.",
              file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # The refresh token is a standing key to the channel: owner-only from
    # the moment it exists, never world-readable even for an instant.
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(args.out, 0o600)
    # RUN WITH SUDO, THE BOT COULD NOT READ IT: a root-owned 0600 file in a
    # folder the service user owns (scan, 24 Oct 2026). Handed to whoever
    # owns the folder it was written into.
    folder = args.out.parent.stat()
    if hasattr(os, "geteuid") and os.geteuid() == 0 and folder.st_uid != 0:
        os.chown(args.out, folder.st_uid, folder.st_gid)
    print(f"wrote {args.out} with scopes:\n  " + "\n  ".join(scopes))
    print(f"set {setting}={args.out} in .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
