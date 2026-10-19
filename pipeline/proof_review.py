"""Watching a proof on the page: a strip of its frames, and his fault notes.

He reports what is wrong with a clip as a numbered list with timestamps. On
the page he watches the proof, presses `n` where something is off and types
what; the notes are kept beside the script, in time order, and come back as
the same numbered list he would have typed, ready to paste to a thread.

The strip is a row of small frames across the whole proof, so a glance shows
whether the room, the plates and the cuts are where they should be before he
plays a second. It is drawn once per proof (by the file's mtime) on a thread
of its own; the page shows it when it is there.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

STRIP_FRAMES = 24
STRIP_WIDTH = 320
_building: set[str] = set()
_lock = threading.Lock()


def _strip_dir(video: Path) -> Path:
    v = Path(video)
    return v.parent / "proof_frames" / f"{v.stem}_{int(v.stat().st_mtime)}"


def frame_strip(video: Path, n: int = STRIP_FRAMES) -> list[tuple[float, Path]]:
    """`n` frames spread across the video, drawn now (or read back when they
    already were for this file's mtime)."""
    from pipeline.render_common import ffprobe_duration

    video = Path(video)
    out = _strip_dir(video)
    index = out / "index.json"
    if index.is_file():
        return _read_index(index)
    duration = ffprobe_duration(video)
    if duration <= 0:
        return []
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n):
        t = round(duration * (i + 0.5) / n, 2)
        p = out / f"f_{i:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t),
             "-i", str(video), "-frames:v", "1", "-vf", f"scale={STRIP_WIDTH}:-2",
             "-q:v", "5", str(p)], capture_output=True, timeout=120)
        if p.is_file():
            rows.append((t, p))
    index.write_text(json.dumps([[t, p.name] for t, p in rows]), encoding="utf-8")
    # Older strips of the same proof are a re-render's leftovers.
    for old in out.parent.glob(f"{video.stem}_*"):
        if old != out and old.is_dir():
            for f in old.iterdir():
                f.unlink(missing_ok=True)
            old.rmdir()
    return rows


def _read_index(index: Path) -> list[tuple[float, Path]]:
    try:
        rows = json.loads(index.read_text(encoding="utf-8"))
        return [(float(t), index.parent / str(name)) for t, name in rows]
    except (OSError, ValueError, TypeError):
        return []


def cached_strip(video: Path) -> list[tuple[float, Path]]:
    """The strip if it is drawn; otherwise none, and it starts drawing."""
    video = Path(video)
    if not video.is_file():
        return []
    index = _strip_dir(video) / "index.json"
    if index.is_file():
        return _read_index(index)
    key = str(index)
    with _lock:
        if key in _building:
            return []
        _building.add(key)

    def build():
        try:
            frame_strip(video)
        except Exception as e:  # noqa: BLE001 - a strip is never the proof
            log.warning("proof strip for %s failed: %s", video.name, e)
        finally:
            with _lock:
                _building.discard(key)

    threading.Thread(target=build, daemon=True, name="proof-strip").start()
    return []


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

def notes_path(ws_path: Path, fmt: str) -> Path:
    return Path(ws_path) / f"proof_notes_{fmt}.json"


def load_notes(ws_path: Path, fmt: str) -> list[dict]:
    try:
        rows = json.loads(notes_path(ws_path, fmt).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = [{"t": float(r.get("t", 0)), "text": str(r.get("text", "")),
            "at": str(r.get("at", ""))}
           for r in rows if isinstance(r, dict) and str(r.get("text", "")).strip()]
    return sorted(out, key=lambda r: r["t"])


def _save(ws_path: Path, fmt: str, notes: list[dict]) -> list[dict]:
    notes = sorted(notes, key=lambda r: r["t"])
    path = notes_path(ws_path, fmt)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(notes, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return notes


def add_note(ws_path: Path, fmt: str, t: float, text: str) -> list[dict]:
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("the note is empty")
    notes = load_notes(ws_path, fmt)
    notes.append({"t": round(max(float(t), 0.0), 2), "text": text[:500],
                  "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return _save(ws_path, fmt, notes)


def drop_note(ws_path: Path, fmt: str, number: int) -> list[dict]:
    """Drop note `number` as the list numbers it (1 is the first)."""
    notes = load_notes(ws_path, fmt)
    if not 1 <= number <= len(notes):
        raise ValueError(f"there is no note {number}")
    del notes[number - 1]
    return _save(ws_path, fmt, notes)


def clock(t: float) -> str:
    s = int(t)
    return f"{s // 60}:{s % 60:02d}"


def fault_list(notes: list[dict]) -> str:
    """His notes as the numbered list he sends: `1. 0:12 the chart is late`."""
    return "\n".join(f"{i}. {clock(n['t'])} {n['text']}"
                     for i, n in enumerate(notes, 1))
