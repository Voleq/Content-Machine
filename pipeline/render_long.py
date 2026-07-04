"""LONG jump-cut engine — 16:9 deadpan deep-dive (§7.2).

Structure:
  * clean audio from the tag-stripped narration (cached TTS)
  * `build_long_timeline` resolves every tag to its spoken word
  * `plan_long_segments` tiles the full duration with 3–5s cuts
  * the whole video is ONE ffmpeg filter_complex: per-segment trim ->
    concat -> stamp/ticker/disclaimer/glitch overlays -> libass captions,
    plus VO + music bed + SFX in a single amix — one final encode
  * draft mode reuses the same cached audio and graph at low res /
    ultrafast (never re-calls TTS §7.2)

B-roll lands exactly on its anchor word; `[SHOW REFINITIV]` flashes the
normalized screenshot full-screen with a pre-rendered glitch overlay and
its `[SOUND]` if the script placed one.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PIL import Image

from config import Settings
from pipeline.broll import BrollManager
from pipeline.models import CueKind, LongScript, SFX_KEYS, TTSResult
from pipeline.rasters import (
    GREEN,
    RED,
    build_karaoke_ass,
    frames_to_alpha_clip,
    simple_text,
    stamp_drop_frames,
)
from pipeline.refinitiv import prepare_screenshot
from pipeline.render_common import (
    AudioTrack,
    CompositeSpec,
    OverlayLayer,
    RenderError,
    composite_video,
    encode_profile,
    ffprobe_duration,
)
from pipeline.timeline import build_long_timeline, plan_long_segments

log = logging.getLogger(__name__)

_FILLER_LOOKS = (
    "null",                                     # plain desk
    "eq=brightness=0.03:saturation=1.05",       # slightly lifted
    "crop=iw*0.94:ih*0.94,scale={W}:{H}",       # subtle punch-in
    "hflip",                                    # mirrored grain
)


def render_long(
    script: LongScript,
    tts: TTSResult,
    workspace: Path,
    settings: Settings,
    broll: BrollManager | None = None,
    *,
    draft: bool = False,
    broll_overrides: dict[str, int] | None = None,
    as_of: str = "",
) -> tuple[Path, Path]:
    """Render the LONG (or its low-res draft). Returns (mp4, manifest)."""
    broll = broll or BrollManager(settings)
    duration = tts.duration_s
    cues = build_long_timeline(script, tts.words, duration)
    segments, seg_warnings = plan_long_segments(
        cues, duration,
        min_cut_s=settings.long_min_cut_s,
        max_cut_s=settings.long_max_cut_s,
        broll_hold_s=settings.broll_max_clip_s * 0.65,
    )
    for w in seg_warnings:
        log.warning("segment plan: %s", w)

    FW, FH = settings.long_resolution          # full spec
    if draft:
        W = int(FW * settings.draft_scale) // 2 * 2
        H = int(FH * settings.draft_scale) // 2 * 2
    else:
        W, H = FW, FH

    rdir = workspace / ("render_long_draft" if draft else "render_long")
    rdir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------ per-segment inputs
    inputs: list[str] = []
    lines: list[str] = []
    seg_meta: list[dict] = []
    filler_bg = settings.assets_dir / "backgrounds" / "desk_wide.png"
    shot_cache: dict[str, Path] = {}

    for i, seg in enumerate(segments):
        seg_len = seg.length
        fit = f"scale={W}:{H}"
        # every chain ends with setsar=1 AFTER the per-variant look — a
        # crop/scale look would otherwise re-derive a non-1:1 SAR and make
        # the concat filter reject the stream
        tail = f",setsar=1,format=yuv420p[s{i}]"
        if seg.kind == "broll":
            clip = broll.resolve(seg.payload["key"], (broll_overrides or {}).get(seg.payload["key"], 0))
            inputs += ["-i", str(clip.path)]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},{fit}{tail}"
            )
            seg_meta.append({"kind": "broll", "key": seg.payload["key"],
                             "source": clip.source, "attribution": clip.attribution,
                             "start": seg.start, "end": seg.end})
        elif seg.kind == "refinitiv":
            fname = seg.payload["file"]
            if fname not in shot_cache:
                shot_cache[fname] = prepare_screenshot(
                    workspace / fname, rdir / f"shot_{Path(fname).stem}.png", settings
                )
            inputs += ["-loop", "1", "-framerate", str(settings.fps),
                       "-t", f"{seg_len + 0.2:.4f}", "-i", str(shot_cache[fname])]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,{fit}{tail}"
            )
            seg_meta.append({"kind": "refinitiv", "file": fname,
                             "start": seg.start, "end": seg.end})
        else:  # filler
            look = _FILLER_LOOKS[seg.payload.get("variant", 0) % len(_FILLER_LOOKS)].format(W=W, H=H)
            inputs += ["-loop", "1", "-framerate", str(settings.fps),
                       "-t", f"{seg_len + 0.2:.4f}", "-i", str(filler_bg)]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"{fit},{look}{tail}"
            )
            seg_meta.append({"kind": "filler", "variant": seg.payload.get("variant", 0),
                             "start": seg.start, "end": seg.end})
        lines.append(chain)

    concat_in = "".join(f"[s{i}]" for i in range(len(segments)))
    lines.append(f"{concat_in}concat=n={len(segments)}:v=1:a=0[vcat]")
    lines.append(f"[vcat]fps={settings.fps}[v0]")

    # ------------------------------------------------------------ layers
    layers: list[OverlayLayer] = []
    px = lambda v: int(round(v * W / 1920))  # noqa: E731  (1920-wide design)

    # glitch flash on every refinitiv reveal (pre-rendered overlay, §7.2)
    glitch = settings.assets_dir / "overlays" / "glitch_noise.mov"
    if glitch.exists():
        glitch_big = rdir / "glitch_scaled.mov"
        if not glitch_big.exists():
            from pipeline.render_common import run_ffmpeg
            run_ffmpeg(["-i", str(glitch),
                        "-vf", f"scale={W}:{H}:flags=neighbor",
                        "-c:v", "png", "-pix_fmt", "rgba", str(glitch_big)])
        for seg in segments:
            if seg.kind == "refinitiv":
                layers.append(OverlayLayer(
                    path=glitch_big, x=0, y=0,
                    t_start=seg.start, t_end=min(seg.start + 0.5, duration),
                    is_video=True, name=f"glitch@{seg.start:.2f}",
                ))

    # verdict stamps ([STAMP] cues) — drop + hold 3s (final stamp holds to end)
    stamp_cues = [c for c in cues if c.kind is CueKind.STAMP]
    for k, c in enumerate(stamp_cues):
        label = c.payload["label"]
        img = Image.open(settings.assets_dir / "stamps" / f"{label}.png").convert("RGBA")
        frames = stamp_drop_frames(img, fps=settings.fps, final_width=px(760))
        clip = frames_to_alpha_clip(frames, settings.fps, rdir / f"stamp_{k}_{label}.mov")
        is_last = k == len(stamp_cues) - 1
        t_end = duration if is_last else min(c.t + 3.0, duration)
        cw, ch = frames[0].size
        layers.append(OverlayLayer(
            path=clip, x=(W - cw) // 2, y=(H - ch) // 2,
            t_start=c.t, t_end=t_end, is_video=True, hold=True,
            name=f"stamp_{label}",
        ))

    # corner bug: ticker + as-of date (§11 keeps the as-of visible)
    bug_text = f"{script.ticker} · audit" + (f" as of {as_of}" if as_of else "")
    bug = simple_text(settings, bug_text, font_size=px(34),
                      fill=(255, 255, 255, 200), stroke_width=2)
    bug_path = rdir / "corner_bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=W - bug.width - px(36), y=px(30),
        t_start=0.0, t_end=duration, name="corner_bug",
    ))

    disc = simple_text(settings, settings.disclaimer_text, font_size=px(26),
                       fill=(235, 235, 235, 190), stroke_width=2)
    disc_path = rdir / "disclaimer.png"
    disc.save(disc_path)
    layers.append(OverlayLayer(
        path=disc_path, x=px(36), y=H - px(52),
        t_start=0.0, t_end=duration, name="disclaimer",
    ))

    # ---------------------------------------------------------- captions
    # kept narrow (max ~22 chars) so a 9:16 center crop (repurpose §6)
    # retains them fully
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_karaoke_ass(
        tts.words, play_res=(W, H), font_size=px(52), margin_v=px(84),
        max_words=4, max_chars=22, duration=duration,
    ))

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, gain_db=0.0)]
    music = settings.assets_dir / "music" / "deadpan_bed.m4a"
    if music.exists():
        audio.append(AudioTrack(path=music, gain_db=settings.music_gain_db, loop=True))
    for c in cues:
        if c.kind is CueKind.SOUND and c.payload.get("key") in SFX_KEYS:
            sfx = settings.assets_dir / "sfx" / f"{c.payload['key']}.wav"
            if sfx.exists():
                audio.append(AudioTrack(path=sfx, start_s=c.t, gain_db=settings.sfx_gain_db))
    stamp_hit = settings.assets_dir / "sfx" / "stamp_hit.wav"
    if stamp_hit.exists():
        for c in stamp_cues:
            audio.append(AudioTrack(path=stamp_hit, start_s=c.t, gain_db=settings.sfx_gain_db + 3))

    # ------------------------------------------------------------ encode
    spec = CompositeSpec(
        base_input_args=inputs,
        base_graph_lines=lines,
        layers=layers,
        audio=audio,
        ass_path=ass_path,
        fonts_dir=settings.fonts_dir,
        duration=duration,
        fps=settings.fps,
    )
    out_path = workspace / ("long_draft.mp4" if draft else "long_final.mp4")
    profile = encode_profile(settings, "long", draft=draft)
    composite_video(spec, profile, settings.audio_bitrate, out_path)

    rendered = ffprobe_duration(out_path)
    if abs(rendered - duration) > 0.7:
        raise RenderError(
            f"rendered duration {rendered:.2f}s deviates from the audio master "
            f"clock {duration:.2f}s"
        )

    manifest_path = workspace / ("render_long_draft_manifest.json" if draft
                                 else "render_long_manifest.json")
    attributions = sorted({m["attribution"] for m in seg_meta
                           if m.get("attribution")})
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "draft": draft,
        "duration": duration,
        "resolution": [W, H],
        "cues": [c.model_dump() for c in cues],
        "segments": seg_meta,
        "segment_warnings": seg_warnings,
        "attributions": attributions,
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2))
    return out_path, manifest_path
