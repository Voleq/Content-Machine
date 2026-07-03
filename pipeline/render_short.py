"""SHORT scene engine — 9:16, ~55–60s "forensic audit" (§7.1).

Every visual event's time comes from `build_short_timeline` (the master
clock); this module only turns cues into rasters, alpha clips and one
FFmpeg filtergraph. There are NO hardcoded scene timings here — grep for
`between(t` lands only on cue-derived values.

Scene stack (bottom → top):
  desk background
  closed folder (cold open) → whip-pan clip → open folder
  highlight sweep (under the typed line), typewriter data lines
  verdict stamp drop
  CTA card, hook card, persistent disclaimer
  word-synced karaoke captions (libass)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PIL import Image, ImageDraw

from config import Settings
from pipeline.models import CueKind, ShortScript, TTSResult
from pipeline.rasters import (
    DISPLAY_BOLD,
    GREEN,
    RED,
    build_karaoke_ass,
    frames_to_alpha_clip,
    highlight_sweep_frames,
    load_font,
    simple_text,
    stamp_drop_frames,
    text_panel,
    typing_frames,
    whip_pan_frames,
)
from pipeline.render_common import (
    AudioTrack,
    CompositeSpec,
    OverlayLayer,
    RenderError,
    composite_video,
    encode_profile,
    ffprobe_duration,
)
from pipeline.timeline import build_short_timeline

log = logging.getLogger(__name__)


def render_short(
    script: ShortScript,
    tts: TTSResult,
    workspace: Path,
    settings: Settings,
    out_name: str = "short_final.mp4",
) -> tuple[Path, Path]:
    """Render the SHORT. Returns (mp4_path, manifest_path)."""
    duration = tts.duration_s
    cues = build_short_timeline(script, tts.words, duration)
    for c in cues:
        if c.fallback:
            log.warning("cue %s used a fallback position (t=%.2fs)", c.kind.value, c.t)

    W, H = settings.short_resolution
    s = W / 1080.0  # design coordinates are 1080-wide

    def px(v: float) -> int:
        return int(round(v * s))

    rdir = workspace / "render_short"
    rdir.mkdir(parents=True, exist_ok=True)

    accent = GREEN if script.verdict.is_laudatory else RED
    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    whip = next(c for c in cues if c.kind is CueKind.WHIP_PAN)
    stamp_cue = next(c for c in cues if c.kind is CueKind.STAMP)
    cta = next(c for c in cues if c.kind is CueKind.CTA)
    data_cues = [c for c in cues if c.kind is CueKind.DATA_LINE]
    hl_cues = [c for c in cues if c.kind is CueKind.HIGHLIGHT]
    whip_end = whip.t + float(whip.payload["duration"])

    layers: list[OverlayLayer] = []

    # ------------------------------------------------------ folder props
    closed = Image.open(settings.assets_dir / "backgrounds" / "folder_closed.png").convert("RGBA")
    d = ImageDraw.Draw(closed)
    tfont = load_font(settings, DISPLAY_BOLD, 140)
    tw = d.textlength(script.ticker, font=tfont)
    d.text(((closed.width - tw) / 2, 680), script.ticker, font=tfont, fill=(88, 60, 28, 255))
    closed = closed.resize((px(760), int(closed.height * px(760) / closed.width)), Image.LANCZOS)
    closed_pos = (int((W - closed.width) / 2), px(500))

    opened = Image.open(settings.assets_dir / "backgrounds" / "folder_open.png").convert("RGBA")
    opened = opened.resize((px(1000), int(opened.height * px(1000) / opened.width)), Image.LANCZOS)
    open_pos = (int((W - opened.width) / 2), px(540))

    closed_path = rdir / "folder_closed_ticker.png"
    closed.save(closed_path)
    open_path = rdir / "folder_open.png"
    opened.save(open_path)

    layers.append(OverlayLayer(
        path=closed_path, x=closed_pos[0], y=closed_pos[1],
        t_start=0.0, t_end=whip.t, name="folder_closed",
    ))

    whip_clip = frames_to_alpha_clip(
        whip_pan_frames(closed, opened, (W, H), (closed_pos, open_pos),
                        fps=settings.fps, duration=float(whip.payload["duration"])),
        settings.fps, rdir / "whip_pan.mov",
    )
    layers.append(OverlayLayer(
        path=whip_clip, x=0, y=0, t_start=whip.t, t_end=whip_end,
        is_video=True, name="whip_pan",
    ))
    layers.append(OverlayLayer(
        path=open_path, x=open_pos[0], y=open_pos[1],
        t_start=max(whip_end - 1.0 / settings.fps, 0), t_end=duration, name="folder_open",
    ))

    # ------------------------------------- highlight (UNDER the line text)
    line_h = px(140)
    line_x = open_pos[0] + px(64)
    line_y0 = open_pos[1] + px(72)
    for i, c in enumerate(hl_cues):
        idx = int(c.payload["line_index"])
        sweep = frames_to_alpha_clip(
            highlight_sweep_frames(opened.width - px(112), px(116), c.payload["color"],
                                   fps=settings.fps),
            settings.fps, rdir / f"highlight_{i}.mov",
        )
        layers.append(OverlayLayer(
            path=sweep, x=open_pos[0] + px(52), y=line_y0 - px(10) + idx * line_h,
            t_start=c.t, t_end=duration, is_video=True, hold=True,
            name=f"highlight_line{idx}",
        ))

    # -------------------------------------------------- typewriter lines
    for c in data_cues:
        i = int(c.payload["index"])
        clip = frames_to_alpha_clip(
            typing_frames(settings, c.payload["text"], font_size=px(46),
                          fps=settings.fps, type_seconds=float(c.payload["type_seconds"])),
            settings.fps, rdir / f"line_{i}.mov",
        )
        layers.append(OverlayLayer(
            path=clip, x=line_x, y=line_y0 + i * line_h,
            t_start=c.t, t_end=duration, is_video=True, hold=True,
            name=f"data_line_{i}",
        ))

    # ------------------------------------------------------- stamp drop
    stamp_png = settings.assets_dir / "stamps" / f"{stamp_cue.payload['label']}.png"
    stamp_img = Image.open(stamp_png).convert("RGBA")
    stamp_clip_frames = stamp_drop_frames(stamp_img, fps=settings.fps, final_width=px(900))
    stamp_clip = frames_to_alpha_clip(stamp_clip_frames, settings.fps, rdir / "stamp.mov")
    cw, ch = stamp_clip_frames[0].size
    layers.append(OverlayLayer(
        path=stamp_clip, x=int((W - cw) / 2), y=px(1080) - ch // 2,
        t_start=stamp_cue.t, t_end=duration, is_video=True, hold=True, name="stamp",
    ))

    # ------------------------------------------------- cards + disclaimer
    hook_img = text_panel(settings, hook.payload["text"], width=px(960),
                          font_size=px(68), accent=accent)
    hook_path = rdir / "hook.png"
    hook_img.save(hook_path)
    layers.append(OverlayLayer(
        path=hook_path, x=int((W - hook_img.width) / 2), y=px(150),
        t_start=0.0, t_end=float(hook.payload["until"]), name="hook",
    ))

    cta_img = text_panel(settings, cta.payload["text"], width=px(880),
                         font_size=px(52), accent=accent, bg=(20, 16, 12, 235))
    cta_path = rdir / "cta.png"
    cta_img.save(cta_path)
    layers.append(OverlayLayer(
        path=cta_path, x=int((W - cta_img.width) / 2), y=px(1430),
        t_start=cta.t, t_end=duration, fade_in=0.25, name="cta",
    ))

    disc_img = simple_text(settings, settings.disclaimer_text, font_size=px(30),
                           fill=(235, 235, 235, 210), stroke_width=2)
    disc_path = rdir / "disclaimer.png"
    disc_img.save(disc_path)
    layers.append(OverlayLayer(
        path=disc_path, x=int((W - disc_img.width) / 2), y=H - px(70),
        t_start=0.0, t_end=duration, name="disclaimer",
    ))

    # ---------------------------------------------------------- captions
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_karaoke_ass(
        tts.words, play_res=(W, H), font_size=px(64), margin_v=px(150),
        accent_rgb=accent, duration=duration,
    ))

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, start_s=0.0, gain_db=0.0)]
    whoosh = settings.assets_dir / "sfx" / "whoosh.wav"
    stamp_hit = settings.assets_dir / "sfx" / "stamp_hit.wav"
    if whoosh.exists():
        audio.append(AudioTrack(path=whoosh, start_s=whip.t, gain_db=settings.sfx_gain_db))
    if stamp_hit.exists():
        audio.append(AudioTrack(path=stamp_hit, start_s=stamp_cue.t, gain_db=settings.sfx_gain_db + 3))

    # ------------------------------------------------------------ encode
    desk = settings.assets_dir / "backgrounds" / "desk_dark.png"
    spec = CompositeSpec(
        base_input_args=[
            "-loop", "1", "-framerate", str(settings.fps),
            "-t", f"{duration:.3f}", "-i", str(desk),
        ],
        base_filter=f"scale={W}:{H},setsar=1,format=yuv420p",
        layers=layers,
        audio=audio,
        ass_path=ass_path,
        fonts_dir=settings.fonts_dir,
        duration=duration,
        fps=settings.fps,
    )
    out_path = workspace / out_name
    composite_video(spec, encode_profile(settings, "short"), settings.audio_bitrate, out_path)

    rendered = ffprobe_duration(out_path)
    if abs(rendered - duration) > 0.5:
        raise RenderError(
            f"rendered duration {rendered:.2f}s deviates from the audio master "
            f"clock {duration:.2f}s"
        )

    manifest_path = workspace / "render_short_manifest.json"
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "verdict": script.verdict.value,
        "duration": duration,
        "cues": [c.model_dump() for c in cues],
        "layers": [
            {"name": l.name, "t_start": l.t_start, "t_end": l.t_end, "x": l.x, "y": l.y}
            for l in layers
        ],
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2))
    return out_path, manifest_path
