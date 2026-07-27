"""YouTube upload and retention feedback (P3.5 + addendum 5b).

`publish.py` builds the upload package — titles, description with chapter
timestamps, tags, pinned comment. This puts it on YouTube and reads back what
happened.

Two halves:

* **Upload.** Data API v3 resumable upload, always as `private` or
  `scheduled` — never `public` on the way out of a machine. Long-form is not
  news-bound and gets made in batches, so the uploader takes an explicit
  **publish datetime per video** (5b): render two on a Sunday, schedule one
  for Friday evening and one for the Sunday after, and nothing further is
  required of the operator.
* **Retention.** The Analytics API returns audience-retention as relative
  positions through the video. Mapped onto the chapter timestamps, that
  becomes "chapter three is where they leave" — which is the only way this
  ever produces evidence about which chapter *types* hold attention rather
  than an opinion about it.

Everything is optional and degrades: no credentials means the operator gets
the package to upload by hand, which is exactly how it worked before.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from config import Settings

log = logging.getLogger(__name__)

RECORDS_FILE = "published.json"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)

# YouTube rejects anything else on these two, and finding out at upload time
# after a 40-minute render is a bad way to learn it.
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX_CHARS = 500


class YouTubeUnavailable(RuntimeError):
    """No credentials or no client library — hand the package to the operator."""


class UploadError(RuntimeError):
    pass


@dataclass
class VideoRecord:
    ticker: str
    video_id: str
    title: str
    privacy: str                        # private | scheduled | public
    publish_at: str = ""                # ISO, when scheduled
    uploaded_at: str = ""
    workdate: str = ""
    chapters: list = field(default_factory=list)   # [(mm:ss, title), …]
    duration_s: float = 0.0
    retention: dict = field(default_factory=dict)

    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"

    def to_json(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Validation — cheaper to catch here than after the upload starts.
# --------------------------------------------------------------------------


def validate_package(title: str, description: str,
                     tags: Sequence[str]) -> list[str]:
    """Problems that would make YouTube reject or silently mangle the upload."""
    problems: list[str] = []
    if not title.strip():
        problems.append("the title is empty")
    if len(title) > TITLE_MAX:
        problems.append(f"the title is {len(title)} chars (max {TITLE_MAX})")
    if "<" in title or ">" in title:
        problems.append("angle brackets in the title are rejected by YouTube")
    if len(description) > DESCRIPTION_MAX:
        problems.append(
            f"the description is {len(description)} chars (max {DESCRIPTION_MAX})")
    total_tags = sum(len(t) + 1 for t in tags)
    if total_tags > TAGS_MAX_CHARS:
        problems.append(f"tags total {total_tags} chars (max {TAGS_MAX_CHARS})")
    return problems


def resolve_publish_at(when: str | datetime | None,
                       now: datetime | None = None) -> datetime | None:
    """Parse a requested publish time into an aware UTC datetime (5b).

    Accepts an ISO timestamp, `YYYY-MM-DD HH:MM`, or a bare date (which means
    the configured hour on that day). A time in the past is an error rather
    than a silent immediate publish — "I meant last Friday" should not put a
    video live now.
    """
    if when is None or when == "":
        return None
    now = now or datetime.now(timezone.utc)
    if isinstance(when, datetime):
        dt = when
    else:
        text = str(when).strip().replace("/", "-")
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(
                f"{when!r} is not a time I can read — try 2026-08-07 18:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= now:
        raise ValueError(
            f"{dt.isoformat()} is in the past — a scheduled publish has to be "
            f"in the future (leave it out to upload as private).")
    return dt


# --------------------------------------------------------------------------
# The API seam.
# --------------------------------------------------------------------------


class YouTubeClient:
    """Thin wrapper over the Data + Analytics APIs.

    Not exercised by the suite — there are no credentials here and uploading
    to a real channel from a test would be its own kind of disaster. The
    interface is small on purpose so a fake can stand in for all of it.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._youtube: Any = None
        self._analytics: Any = None

    def _credentials(self):
        try:
            from google.oauth2.credentials import Credentials
        except ImportError as e:
            raise YouTubeUnavailable(
                "google-auth is not installed (pip install '.[youtube]')") from e
        path = Path(self.settings.youtube_credentials or "")
        if not path.exists():
            raise YouTubeUnavailable(
                f"no YouTube credentials at {path or '(unset)'} — the upload "
                f"package is still yours to post by hand.")
        try:
            return Credentials.from_authorized_user_file(str(path), list(SCOPES))
        except Exception as e:  # noqa: BLE001
            raise YouTubeUnavailable(f"credentials at {path} unreadable: {e}") from e

    def _build(self, name: str, version: str):
        try:
            from googleapiclient.discovery import build
        except ImportError as e:
            raise YouTubeUnavailable(
                "google-api-python-client is not installed "
                "(pip install '.[youtube]')") from e
        return build(name, version, credentials=self._credentials(),
                     cache_discovery=False)

    def upload(self, path: Path, body: dict) -> str:
        """Resumable upload. Returns the video id."""
        from googleapiclient.http import MediaFileUpload

        if self._youtube is None:
            self._youtube = self._build("youtube", "v3")
        media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024,
                                resumable=True, mimetype="video/mp4")
        request = self._youtube.videos().insert(
            part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("youtube upload %d%%", int(status.progress() * 100))
        vid = response.get("id")
        if not vid:
            raise UploadError(f"upload returned no video id: {response}")
        return vid

    def comment(self, video_id: str, text: str) -> None:
        if self._youtube is None:
            self._youtube = self._build("youtube", "v3")
        self._youtube.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id,
                              "topLevelComment": {"snippet":
                                                  {"textOriginal": text}}}},
        ).execute()

    def retention(self, video_id: str, start: str, end: str) -> list[dict]:
        """Relative audience retention rows: [{elapsed_ratio, watch_ratio}, …]."""
        if self._analytics is None:
            self._analytics = self._build("youtubeAnalytics", "v2")
        resp = self._analytics.reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
        ).execute()
        rows = resp.get("rows") or []
        return [{"elapsed_ratio": float(r[0]), "watch_ratio": float(r[1])}
                for r in rows if len(r) >= 2]


def available(settings: Settings) -> tuple[bool, str]:
    if not settings.youtube_enabled:
        return False, "YouTube upload is switched off (YOUTUBE_ENABLED=false)."
    if settings.mock_mode:
        return False, "MOCK_MODE — nothing is uploaded."
    if not settings.youtube_credentials:
        return False, "YOUTUBE_CREDENTIALS is not set."
    if not Path(settings.youtube_credentials).exists():
        return False, f"no credentials file at {settings.youtube_credentials}."
    try:
        import googleapiclient  # noqa: F401
    except ImportError:
        return False, "google-api-python-client is not installed."
    return True, "YouTube upload is available"


# --------------------------------------------------------------------------
# Upload.
# --------------------------------------------------------------------------


def build_body(package, *, title: str = "", publish_at: datetime | None = None,
               settings: Settings | None = None) -> dict:
    """The Data API insert body. Private unless a publish time says otherwise."""
    chosen = title or (package.titles[0] if package.titles else package.ticker)
    status: dict = {"selfDeclaredMadeForKids": False}
    if publish_at is not None:
        # `publishAt` only takes effect while the video is private; setting
        # both is how a scheduled publish is expressed.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
    else:
        status["privacyStatus"] = "private"
    body = {
        "snippet": {
            "title": chosen[:TITLE_MAX],
            "description": package.description[:DESCRIPTION_MAX],
            "tags": list(package.tags),
            "categoryId": (settings.youtube_category_id if settings else "25"),
        },
        "status": status,
    }
    return body


def upload_video(video: Path, package, settings: Settings, *,
                 title: str = "", publish_at: str | datetime | None = None,
                 workdate: str = "", chapters: Sequence = (),
                 duration_s: float = 0.0,
                 client: YouTubeClient | None = None,
                 now: datetime | None = None) -> VideoRecord:
    """Upload as private (or scheduled), pin the comment, record it.

    Never public on the way out: a scheduled publish is the most this will do
    unattended, and everything else waits for a human to flip it.
    """
    if not video.exists():
        raise UploadError(f"no file to upload at {video}")
    when = resolve_publish_at(publish_at, now)

    chosen = title or (package.titles[0] if package.titles else package.ticker)
    problems = validate_package(chosen, package.description, package.tags)
    if problems:
        raise UploadError("the upload package would be rejected: "
                          + "; ".join(problems))

    if client is None:
        ok, why = available(settings)
        if not ok:
            raise YouTubeUnavailable(why)
        client = YouTubeClient(settings)

    body = build_body(package, title=chosen, publish_at=when, settings=settings)
    video_id = client.upload(video, body)

    if package.pinned_comment:
        try:
            client.comment(video_id, package.pinned_comment)
        except Exception as e:  # noqa: BLE001 - the video is up; a comment is not
            log.warning("pinned comment failed for %s: %s", video_id, e)

    record = VideoRecord(
        ticker=package.ticker, video_id=video_id, title=chosen,
        privacy="scheduled" if when else "private",
        publish_at=when.isoformat() if when else "",
        uploaded_at=(now or datetime.now(timezone.utc)).isoformat(),
        workdate=workdate, chapters=[list(c) for c in chapters],
        duration_s=duration_s)
    VideoLog(settings).record(record)
    log.info("youtube: %s uploaded as %s%s", video_id, record.privacy,
             f" for {record.publish_at}" if when else "")
    return record


# --------------------------------------------------------------------------
# The record of what has been published.
# --------------------------------------------------------------------------


class VideoLog:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.state_dir / RECORDS_FILE

    def _all(self) -> list[dict]:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            return rows if isinstance(rows, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    def record(self, video: VideoRecord) -> None:
        rows = [r for r in self._all() if r.get("video_id") != video.video_id]
        rows.append(video.to_json())
        self._save(rows)

    def get(self, video_id: str) -> VideoRecord | None:
        for r in self._all():
            if r.get("video_id") == video_id:
                return VideoRecord(**r)
        return None

    def all(self) -> list[VideoRecord]:
        return [VideoRecord(**r) for r in self._all()]

    def for_ticker(self, ticker: str) -> list[VideoRecord]:
        return [v for v in self.all() if v.ticker == ticker.upper()]

    def update_retention(self, video_id: str, retention: dict) -> bool:
        rows = self._all()
        for r in rows:
            if r.get("video_id") == video_id:
                r["retention"] = retention
                self._save(rows)
                return True
        return False

    def scheduled(self) -> list[VideoRecord]:
        return sorted((v for v in self.all() if v.privacy == "scheduled"),
                      key=lambda v: v.publish_at)


# --------------------------------------------------------------------------
# Retention, mapped onto chapters.
# --------------------------------------------------------------------------


def _seconds(stamp: str) -> float:
    parts = [p for p in re.split(r"[:.]", stamp.strip()) if p.isdigit()]
    if not parts:
        return 0.0
    parts = [int(p) for p in parts[:3]]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def map_retention_to_chapters(rows: Sequence[dict],
                              chapters: Sequence,
                              duration_s: float) -> list[dict]:
    """Turn relative retention into "which chapter loses them".

    The API returns positions as a ratio through the video, so without the
    chapter timestamps and the duration the numbers say nothing actionable.
    With them, each chapter gets the average watch ratio over its own span and
    the drop across it — and the drop is the interesting number, because a
    chapter that starts low may simply be late in the video.
    """
    if not rows or not chapters or duration_s <= 0:
        return []
    bounds: list[tuple[str, float, float]] = []
    stamps = [(_seconds(str(c[0])), str(c[1])) for c in chapters]
    for i, (start, title) in enumerate(stamps):
        end = stamps[i + 1][0] if i + 1 < len(stamps) else duration_s
        if end > start:
            bounds.append((title, start, end))

    ordered = sorted(rows, key=lambda r: r["elapsed_ratio"])
    out: list[dict] = []
    for title, start, end in bounds:
        inside = [r for r in ordered
                  if start <= r["elapsed_ratio"] * duration_s < end]
        if not inside:
            continue
        avg = sum(r["watch_ratio"] for r in inside) / len(inside)
        out.append({
            "chapter": title,
            "start_s": round(start, 1),
            "end_s": round(end, 1),
            "avg_watch_ratio": round(avg, 4),
            "drop": round(inside[0]["watch_ratio"] - inside[-1]["watch_ratio"], 4),
        })
    return out


def retention_report(mapped: Sequence[dict]) -> str:
    """The operator-facing read. Names the worst chapter, because that is the
    one worth changing."""
    if not mapped:
        return "No retention data yet — YouTube needs a day or two of views."
    lines = ["📉 Retention by chapter"]
    for row in mapped:
        bar = "█" * max(1, round(row["avg_watch_ratio"] * 20))
        lines.append(f"  {row['avg_watch_ratio'] * 100:5.1f}% {bar} "
                     f"{row['chapter'][:40]}")
    worst = max(mapped, key=lambda r: r["drop"])
    lines.append(f"\nBiggest drop-off: {worst['chapter']} "
                 f"(−{worst['drop'] * 100:.1f} points across it)")
    return "\n".join(lines)


def pull_retention(video_id: str, settings: Settings, *,
                   client: YouTubeClient | None = None,
                   today: datetime | None = None) -> dict:
    """Fetch retention for one video and store it against its record.

    Degrades: a video too new to have data, or no credentials, returns a
    status rather than raising — this is a feedback loop, not a dependency.
    """
    log_ = VideoLog(settings)
    record = log_.get(video_id)
    if record is None:
        return {"status": "unknown video", "video_id": video_id}
    if client is None:
        ok, why = available(settings)
        if not ok:
            return {"status": "unavailable", "reason": why}
        client = YouTubeClient(settings)

    now = today or datetime.now(timezone.utc)
    start = (now - timedelta(days=settings.retention_window_days)).date().isoformat()
    try:
        rows = client.retention(video_id, start, now.date().isoformat())
    except Exception as e:  # noqa: BLE001 - feedback must never break anything
        log.warning("retention pull failed for %s: %s", video_id, e)
        return {"status": "unavailable", "reason": str(e)[:160]}

    mapped = map_retention_to_chapters(rows, record.chapters, record.duration_s)
    payload = {"status": "ok", "video_id": video_id, "rows": len(rows),
               "chapters": mapped, "pulled_at": now.isoformat()}
    log_.update_retention(video_id, payload)
    return payload


def chapter_type_evidence(settings: Settings) -> list[dict]:
    """Across every video with retention, which chapter TITLES hold attention.

    The point of storing retention per chapter rather than per video: one
    video's drop-off is an anecdote, the same chapter type dropping across
    eight of them is evidence.
    """
    totals: dict[str, list[float]] = {}
    for video in VideoLog(settings).all():
        for row in (video.retention or {}).get("chapters", []):
            key = str(row.get("chapter", "")).strip().lower()
            if key:
                totals.setdefault(key, []).append(float(row.get("avg_watch_ratio", 0)))
    out = [{"chapter": k, "videos": len(v), "avg_watch_ratio": round(sum(v) / len(v), 4)}
           for k, v in totals.items() if v]
    return sorted(out, key=lambda r: r["avg_watch_ratio"])
