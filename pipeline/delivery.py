"""Pluggable delivery (§9.4): gdrive (default) | s3 | telegram | local.

Google Drive is the recommended default: organized dated archive
(/DueDiligenceDesk/<TICKER>/<date>/), shareable link, no bot upload cap,
and it stages files for later YouTube/TikTok upload. Implemented with
google-auth (service account or OAuth refresh-token JSON) + plain httpx
against the Drive REST API — no googleapiclient discovery baggage.

In MOCK_MODE every delivery is forced to the local backend (zero network,
zero external side effects). B-roll attribution is always written beside
the artifact and included in the returned note (§6).
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from config import Settings

log = logging.getLogger(__name__)

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"


class DeliveryError(Exception):
    pass


@dataclass
class DeliveryResult:
    backend: str
    link: str
    note: str = ""
    # set when the bot itself should push the file into the chat
    send_file: Path | None = None
    extra_links: dict[str, str] = field(default_factory=dict)


def _write_attribution(artifact: Path, attributions: list[str]) -> Path | None:
    if not attributions:
        return None
    f = artifact.with_suffix(".attribution.txt")
    f.write_text(
        "B-roll / stock footage credits:\n" + "\n".join(f"- {a}" for a in attributions) + "\n"
    )
    return f


def deliver(
    artifact: Path,
    ticker: str,
    workdate: str,
    settings: Settings,
    attributions: list[str] | None = None,
    extra_files: list[Path] | None = None,
) -> DeliveryResult:
    """Deliver the final MP4 (+ thumbnail etc). Never raises for backend
    trouble without a clear message; MOCK_MODE always lands on `local`."""
    attributions = attributions or []
    extra_files = list(extra_files or [])
    attr_file = _write_attribution(artifact, attributions)
    if attr_file:
        extra_files.append(attr_file)

    backend = "local" if settings.mock_mode else settings.delivery_backend
    note = ""
    if attributions:
        note = "Credits:\n" + "\n".join(f"- {a}" for a in attributions)

    if backend == "gdrive":
        result = GDriveBackend(settings).upload(artifact, ticker, workdate, extra_files)
    elif backend == "s3":
        result = S3Backend(settings).upload(artifact, ticker, workdate, extra_files)
    elif backend == "telegram":
        size_mb = artifact.stat().st_size / 1e6
        if size_mb > settings.telegram_upload_limit_mb and not settings.telegram_api_base_url:
            raise DeliveryError(
                f"{artifact.name} is {size_mb:.0f} MB — over the {settings.telegram_upload_limit_mb} MB "
                f"cloud-bot cap. Use DELIVERY_BACKEND=gdrive (or a self-hosted Bot API server)."
            )
        result = DeliveryResult(backend="telegram", link="(sent in chat)", send_file=artifact)
    else:
        result = _local_deliver(artifact, ticker, workdate, settings, extra_files)

    result.note = note
    return result


def _local_deliver(
    artifact: Path, ticker: str, workdate: str, settings: Settings, extra_files: list[Path]
) -> DeliveryResult:
    dest_dir = settings.workspace_dir / "_delivered" / ticker / workdate
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / artifact.name
    shutil.copy(artifact, dest)
    for f in extra_files:
        if f.exists():
            shutil.copy(f, dest_dir / f.name)
    return DeliveryResult(backend="local", link=f"file://{dest}")


# ---------------------------------------------------------------------------
# Google Drive.
# ---------------------------------------------------------------------------


class GDriveBackend:
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.gdrive_credentials:
            raise DeliveryError(
                "GDRIVE_CREDENTIALS is not set (path to a service-account or "
                "authorized-user JSON)."
            )

    # -------------------------------------------------------------- auth
    def _token(self) -> str:
        import google.auth.transport.requests  # deferred: optional heavy dep

        creds_path = Path(self.settings.gdrive_credentials).expanduser()
        info = json.loads(creds_path.read_text())
        if info.get("type") == "service_account":
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=self.SCOPES
            )
        else:
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(str(creds_path), self.SCOPES)
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    # ------------------------------------------------------------ folders
    def _find_or_create_folder(
        self, client: httpx.Client, name: str, parent: str | None
    ) -> str:
        q = (
            f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        if parent:
            q += f" and '{parent}' in parents"
        r = client.get(f"{DRIVE_API}/files", params={
            "q": q, "fields": "files(id)", "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        })
        r.raise_for_status()
        files = r.json().get("files", [])
        if files:
            return files[0]["id"]
        body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            body["parents"] = [parent]
        r = client.post(f"{DRIVE_API}/files", json=body,
                        params={"supportsAllDrives": "true", "fields": "id"})
        r.raise_for_status()
        return r.json()["id"]

    def _upload_file(self, client: httpx.Client, path: Path, folder_id: str) -> dict:
        meta = {"name": path.name, "parents": [folder_id]}
        r = client.post(
            f"{DRIVE_UPLOAD}/files",
            params={"uploadType": "resumable", "supportsAllDrives": "true",
                    "fields": "id,webViewLink"},
            json=meta,
            headers={"X-Upload-Content-Type": "application/octet-stream"},
        )
        r.raise_for_status()
        session_url = r.headers["Location"]
        with open(path, "rb") as f:
            up = client.put(session_url, content=f, timeout=1800,
                            headers={"Content-Type": "application/octet-stream"})
        up.raise_for_status()
        return up.json()

    def upload(
        self, artifact: Path, ticker: str, workdate: str, extra_files: list[Path]
    ) -> DeliveryResult:
        token = self._token()
        with httpx.Client(
            headers={"Authorization": f"Bearer {token}"}, timeout=120
        ) as client:
            root = self.settings.gdrive_root_folder_id or self._find_or_create_folder(
                client, self.settings.gdrive_folder_name, None
            )
            tdir = self._find_or_create_folder(client, ticker, root)
            ddir = self._find_or_create_folder(client, workdate, tdir)

            main = self._upload_file(client, artifact, ddir)
            file_id = main["id"]
            client.post(
                f"{DRIVE_API}/files/{file_id}/permissions",
                params={"supportsAllDrives": "true"},
                json={"role": "reader", "type": "anyone"},
            ).raise_for_status()
            r = client.get(f"{DRIVE_API}/files/{file_id}",
                           params={"fields": "webViewLink", "supportsAllDrives": "true"})
            r.raise_for_status()
            link = r.json()["webViewLink"]

            extra_links: dict[str, str] = {}
            for f in extra_files:
                if f.exists():
                    extra = self._upload_file(client, f, ddir)
                    extra_links[f.name] = extra.get("webViewLink", "")
        return DeliveryResult(backend="gdrive", link=link, extra_links=extra_links)


# ---------------------------------------------------------------------------
# S3-compatible bucket (optional extra: pip install .[s3]).
# ---------------------------------------------------------------------------


class S3Backend:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.s3_bucket:
            raise DeliveryError("S3_BUCKET is not set.")

    def upload(
        self, artifact: Path, ticker: str, workdate: str, extra_files: list[Path]
    ) -> DeliveryResult:
        try:
            import boto3  # optional dependency
        except ImportError as e:
            raise DeliveryError("boto3 missing — install with: pip install .[s3]") from e
        s3 = boto3.client("s3", region_name=self.settings.s3_region)
        key = f"{self.settings.s3_prefix}/{ticker}/{workdate}/{artifact.name}"
        s3.upload_file(str(artifact), self.settings.s3_bucket, key)
        extra_links: dict[str, str] = {}
        for f in extra_files:
            if f.exists():
                ekey = f"{self.settings.s3_prefix}/{ticker}/{workdate}/{f.name}"
                s3.upload_file(str(f), self.settings.s3_bucket, ekey)
                extra_links[f.name] = ekey
        link = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=7 * 86400,
        )
        return DeliveryResult(backend="s3", link=link, extra_links=extra_links)
