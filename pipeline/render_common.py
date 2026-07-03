"""FFmpeg plumbing shared by every stage: subprocess wrappers, probing,
encode profiles and hardware-encoder detection (§7.3).

Everything renders through `ffmpeg`/`ffprobe` subprocesses (C speed);
Python only builds command lines and small raster assets.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config import Settings, detect_ffmpeg

log = logging.getLogger(__name__)


class RenderError(Exception):
    pass


def run_ffmpeg(args: list[str], timeout: int = 3600) -> None:
    """Run ffmpeg with -y and sane logging; raise RenderError with the
    stderr tail on failure."""
    ffmpeg, _ = detect_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args[:12]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:]
        raise RenderError(f"ffmpeg failed ({proc.returncode}):\n{tail}")


def ffprobe_json(path: Path | str) -> dict:
    _, ffprobe = detect_ffmpeg()
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RenderError(f"ffprobe failed for {path}: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def ffprobe_duration(path: Path | str) -> float:
    """Exact container duration — the master clock reads from here."""
    info = ffprobe_json(path)
    dur = info.get("format", {}).get("duration")
    if dur is None:
        streams = [s for s in info.get("streams", []) if s.get("duration")]
        if not streams:
            raise RenderError(f"no duration found for {path}")
        dur = streams[0]["duration"]
    return float(dur)


@dataclass(frozen=True)
class EncodeProfile:
    vcodec: str
    preset: str
    crf: int
    pix_fmt: str = "yuv420p"

    def video_args(self) -> list[str]:
        args = ["-c:v", self.vcodec, "-pix_fmt", self.pix_fmt]
        if self.vcodec == "libx264":
            args += ["-preset", self.preset, "-crf", str(self.crf)]
        elif self.vcodec == "h264_nvenc":
            args += ["-preset", "p4", "-cq", str(self.crf)]
        elif self.vcodec == "h264_vaapi":
            args += ["-qp", str(self.crf)]
        return args


@lru_cache(maxsize=1)
def detect_hardware_encoder() -> str | None:
    """Return h264_nvenc / h264_vaapi if genuinely usable, else None.

    Listing in `-encoders` is not enough — we do a 0.1s smoke encode.
    """
    ffmpeg, _ = detect_ffmpeg()
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return None
    for enc in ("h264_nvenc", "h264_vaapi"):
        if enc not in out:
            continue
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=c=black:s=128x128:d=0.1", "-c:v", enc, "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode == 0:
            return enc
    return None


def encode_profile(settings: Settings, fmt: str, draft: bool = False) -> EncodeProfile:
    vcodec = "libx264"
    if settings.use_hardware_encoder and not draft:
        hw = detect_hardware_encoder()
        if hw:
            vcodec = hw
    if draft:
        return EncodeProfile(vcodec="libx264", preset=settings.draft_preset, crf=settings.draft_crf)
    crf = settings.short_crf if fmt == "short" else settings.long_crf
    return EncodeProfile(vcodec=vcodec, preset=settings.final_preset, crf=crf)


def concat_audio(chunks: list[Path], out_path: Path, settings: Settings) -> Path:
    """Losslessly-ordered concat of same-codec audio chunks, one AAC encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(chunks) == 1:
        run_ffmpeg(["-i", str(chunks[0]), "-c:a", "aac", "-b:a", settings.audio_bitrate, str(out_path)])
        return out_path
    list_file = out_path.with_suffix(".concat.txt")
    list_file.write_text("".join(f"file '{c.as_posix()}'\n" for c in chunks))
    run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:a", "aac", "-b:a", settings.audio_bitrate, str(out_path),
    ])
    list_file.unlink(missing_ok=True)
    return out_path
