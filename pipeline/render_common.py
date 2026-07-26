"""FFmpeg plumbing shared by every stage: subprocess wrappers, probing,
encode profiles, hardware-encoder detection (§7.3), and the overlay
compositing engine used by both renderers.

Everything renders through `ffmpeg`/`ffprobe` subprocesses (C speed);
Python only builds command lines and small raster assets. Each final MP4
is produced by exactly ONE encode pass over one filtergraph (§2.5).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from config import Settings, detect_ffmpeg

log = logging.getLogger(__name__)


class RenderError(Exception):
    pass


# The render box is somebody's daily-driver desktop. These are set once from
# Settings at startup so every ffmpeg call — including the ones inside
# rasters.py — is capped and de-prioritised without threading the settings
# object through every helper.
_POLITENESS: dict = {"threads": 0, "below_normal": False}


def set_render_politeness(settings) -> None:
    """Apply the encode-politeness knobs process-wide."""
    _POLITENESS["threads"] = settings.resolved_render_threads()
    _POLITENESS["below_normal"] = settings.render_below_normal_priority
    log.info("render politeness: %d ffmpeg threads, below-normal=%s",
             _POLITENESS["threads"], _POLITENESS["below_normal"])


def _politeness_args() -> list[str]:
    """ffmpeg flags that cap CPU use. The filter graph — not the encode — is
    the bottleneck here, so the filter thread pools are capped too."""
    n = _POLITENESS["threads"]
    if not n:
        return []
    return ["-threads", str(n),
            "-filter_threads", str(n),
            "-filter_complex_threads", str(n)]


def _deprioritise(proc: subprocess.Popen) -> None:
    """Drop an already-spawned child below the desktop's priority.

    Done from the parent rather than via `preexec_fn`, which is documented as
    unsafe in a threaded process — and the bot is threaded.
    """
    if not _POLITENESS["below_normal"]:
        return
    try:
        if hasattr(os, "setpriority"):          # POSIX
            os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
    except (OSError, AttributeError, ValueError) as e:
        log.debug("could not de-prioritise pid %s: %s", proc.pid, e)


def _creationflags() -> int:
    """Windows spawns at below-normal directly; POSIX renices after spawn."""
    if _POLITENESS["below_normal"] and sys.platform == "win32":
        return getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    return 0


def _run_polite(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """subprocess.run, but nice to the machine it is running on."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=_creationflags(),
    )
    _deprioritise(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_ffmpeg(args: list[str], timeout: int = 3600) -> None:
    """Run ffmpeg with -y and sane logging; raise RenderError with the
    stderr tail on failure."""
    ffmpeg, _ = detect_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           *_politeness_args(), *args]
    log.debug("ffmpeg %s", " ".join(args[:12]))
    proc = _run_polite(cmd, timeout)
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


def encode_profile(settings: Settings, fmt: str, draft: bool = False,
                   preview: bool = False) -> EncodeProfile:
    vcodec = "libx264"
    if settings.use_hardware_encoder and not (draft or preview):
        hw = detect_hardware_encoder()
        if hw:
            vcodec = hw
    if preview:
        # x264 ultrafast beats the GPU here: the preview is filter-bound and
        # NVENC's setup cost is not worth paying for a throwaway pass.
        return EncodeProfile(vcodec="libx264", preset="ultrafast",
                             crf=settings.preview_crf)
    if draft:
        return EncodeProfile(vcodec="libx264", preset=settings.draft_preset, crf=settings.draft_crf)
    crf = settings.short_crf if fmt == "short" else settings.long_crf
    return EncodeProfile(vcodec=vcodec, preset=settings.final_preset, crf=crf)


# --------------------------------------------------------------------------
# Overlay compositing: one filtergraph, one encode.
# --------------------------------------------------------------------------


@dataclass
class OverlayLayer:
    """One visual layer composited over the base at [t_start, t_end).

    z-order is list order (first = bottom); time is the enable window —
    they are independent, which lets e.g. the highlight sit UNDER the
    typed line while appearing later.
    """

    path: Path
    x: int
    y: int
    t_start: float
    t_end: float
    is_video: bool = False   # alpha .mov clip vs still PNG
    fade_in: float = 0.0
    hold: bool = False       # freeze a clip's last frame through t_end
    name: str = ""           # for the manifest / debugging


@dataclass
class AudioTrack:
    path: Path
    start_s: float = 0.0
    gain_db: float = 0.0
    loop: bool = False       # e.g. the music bed


@dataclass
class CompositeSpec:
    base_input_args: list[str]
    base_filter: str = ""              # single-input base: [0:v]base_filter[v0]
    base_graph_lines: list[str] = field(default_factory=list)
    # multi-input base (e.g. the LONG concat timeline): verbatim filter lines
    # that must end by producing [v0]; overrides base_filter when non-empty
    layers: list[OverlayLayer] = field(default_factory=list)
    audio: list[AudioTrack] = field(default_factory=list)
    ass_path: Path | None = None
    fonts_dir: Path | None = None
    duration: float = 0.0
    fps: int = 30

    def input_count(self) -> int:
        return sum(1 for a in self.base_input_args if a == "-i")


def composite_video(
    spec: CompositeSpec,
    profile: EncodeProfile,
    audio_bitrate: str,
    out_path: Path,
) -> Path:
    """Assemble the full filtergraph (written to a script file to dodge
    argv limits) and run the single final encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = list(spec.base_input_args)
    if spec.base_graph_lines:
        lines = list(spec.base_graph_lines)
    else:
        lines = [f"[0:v]{spec.base_filter}[v0]"]

    idx = spec.input_count()
    for i, layer in enumerate(spec.layers):
        window = layer.t_end - layer.t_start
        if layer.is_video:
            inputs += ["-i", str(layer.path)]
        else:
            inputs += [
                "-loop", "1", "-framerate", str(spec.fps),
                "-t", f"{window + 0.5:.3f}", "-i", str(layer.path),
            ]
        chain = "format=rgba"
        if layer.fade_in > 0:
            chain += f",fade=t=in:st=0:d={layer.fade_in:.3f}:alpha=1"
        if layer.is_video and layer.hold:
            chain += f",tpad=stop_mode=clone:stop_duration={window + 0.5:.3f}"
        chain += f",setpts=PTS-STARTPTS+{layer.t_start:.4f}/TB"
        lines.append(f"[{idx}:v]{chain}[l{i}]")
        lines.append(
            f"[v{i}][l{i}]overlay={layer.x}:{layer.y}"
            f":enable='between(t,{layer.t_start:.4f},{layer.t_end:.4f})'"
            f":eof_action=pass[v{i + 1}]"
        )
        idx += 1

    v_label = f"[v{len(spec.layers)}]"
    if spec.ass_path is not None:
        fonts = f":fontsdir='{spec.fonts_dir}'" if spec.fonts_dir else ""
        lines.append(f"{v_label}subtitles=filename='{spec.ass_path}'{fonts}[vout]")
    else:
        lines.append(f"{v_label}null[vout]")

    a_labels: list[str] = []
    for j, track in enumerate(spec.audio):
        if track.loop:
            inputs += ["-stream_loop", "-1", "-i", str(track.path)]
        else:
            inputs += ["-i", str(track.path)]
        chain = f"atrim=0:{max(spec.duration - track.start_s, 0.1):.3f}"
        if track.start_s > 0:
            chain += f",adelay={int(track.start_s * 1000)}:all=1"
        chain += f",volume={track.gain_db:.1f}dB"
        lines.append(f"[{idx}:a]{chain}[a{j}]")
        a_labels.append(f"[a{j}]")
        idx += 1
    if len(a_labels) == 1:
        lines.append(f"{a_labels[0]}anull[aout]")
    else:
        lines.append(
            f"{''.join(a_labels)}amix=inputs={len(a_labels)}"
            f":duration=longest:normalize=0[aout]"
        )

    script = out_path.with_suffix(".filter.txt")
    script.write_text(";\n".join(lines) + "\n")

    run_ffmpeg([
        *inputs,
        "-filter_complex_script", str(script),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{spec.duration:.3f}", "-r", str(spec.fps),
        *profile.video_args(),
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(out_path),
    ], timeout=7200)
    return out_path


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
