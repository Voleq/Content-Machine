"""LONG jump-cut engine — 16:9 deadpan deep-dive (§5).

Structure:
  * clean audio from the tag-stripped narration (cached TTS)
  * `build_long_timeline` resolves every tag to its spoken word
  * `plan_long_segments` tiles the full duration with fast ~1.5–3s cuts
  * the whole video is ONE ffmpeg filter_complex: per-segment trim ->
    concat -> bug/disclaimer/glitch overlays -> libass captions, plus
    VO + music bed + SFX in a single amix — one final encode
  * draft mode reuses the same cached audio and graph at low res /
    ultrafast (never re-calls TTS)

Segment kinds (§editing — no static desk shots anywhere):
  clip    ironic stock footage (content engine, palette-first)
  img     real operations/product imagery, slow punch-in drift
  meme    freeze-frame from the owned library + boom (first one gets the
          record-scratch rewind)
  chart   auto-generated channel-style chart
  filing  the unnamed-source data screenshot, glitch flash on reveal
  asset   bespoke Claude-Design visual from assets/custom/
  filler  branded backdrop with subtle per-variant looks

Every visual lands exactly on its anchor word; there is no verdict stamp
— the video ends on whatever deadpan line the script wrote.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import Settings
from pipeline.broll import ContentManager
from pipeline.company_data import prepare_screenshot
from pipeline.models import (
    CueKind,
    LongScript,
    SFX_KEYS,
    TTSResult,
    parse_scribble_payload,
)
from pipeline.rasters import (
    build_karaoke_ass,
    doodle_clip,
    frames_to_alpha_clip,
    lower_third,
    scribble_callout_frames,
    simple_text,
)
from pipeline.render_common import (
    AudioTrack,
    CompositeSpec,
    OverlayLayer,
    RenderError,
    composite_video,
    encode_profile,
    ffprobe_duration,
    run_ffmpeg,
)
from pipeline.timeline import build_long_timeline, plan_long_segments

log = logging.getLogger(__name__)

_FILLER_LOOKS = (
    "null",                                     # plain backdrop
    "eq=brightness=0.03:saturation=1.05",       # slightly lifted
    "crop=iw*0.94:ih*0.94,scale={W}:{H}",       # subtle punch-in
    "hflip",                                    # mirrored grain
)


def render_long(
    script: LongScript,
    tts: TTSResult,
    workspace: Path,
    settings: Settings,
    content: ContentManager | None = None,
    *,
    draft: bool = False,
    broll_overrides: dict[str, int] | None = None,
    as_of: str = "",
    company_data=None,
) -> tuple[Path, Path]:
    """Render the LONG (or its low-res draft). Returns (mp4, manifest)."""
    content = content or ContentManager(settings)
    duration = tts.duration_s
    cues = build_long_timeline(script, tts.words, duration)
    doodle_cues = [c for c in cues if c.kind is CueKind.DOODLE]
    scribble_cues = [c for c in cues if c.kind is CueKind.SCRIBBLE]
    segments, seg_warnings = plan_long_segments(
        cues, duration,
        min_cut_s=settings.long_min_cut_s,
        max_cut_s=settings.long_max_cut_s,
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

    website = str(company_data.get("website") or "") if company_data is not None else ""
    overrides = broll_overrides or {}

    # ------------------------------------------------ per-segment inputs
    inputs: list[str] = []
    lines: list[str] = []
    seg_meta: list[dict] = []
    filler_bg = settings.assets_dir / "backgrounds" / "dennis_bg_wide.png"
    shot_cache: dict[str, Path] = {}
    still_pad = f"scale={W}:{H}:force_original_aspect_ratio=decrease," \
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0d12"

    for i, seg in enumerate(segments):
        seg_len = seg.length
        # every chain ends with setsar=1 AFTER the per-variant look — a
        # crop/scale look would otherwise re-derive a non-1:1 SAR and make
        # the concat filter reject the stream
        tail = f",setsar=1,format=yuv420p[s{i}]"
        value = seg.payload.get("value", "")

        def _clip_chain(idx: int) -> str:
            return (
                f"[{idx}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},{still_pad}{tail}"
            )

        if seg.kind == "clip":
            visual = content.resolve_clip(value, overrides.get(value, 0))
            inputs += ["-i", str(visual.path)]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},scale={W}:{H}{tail}"
            )
        elif seg.kind == "filing":
            if value not in shot_cache:
                shot_cache[value] = prepare_screenshot(
                    workspace / value, rdir / f"shot_{Path(value).stem}.png", settings
                )
            visual = None
            inputs += ["-loop", "1", "-framerate", str(settings.fps),
                       "-t", f"{seg_len + 0.2:.4f}", "-i", str(shot_cache[value])]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}{tail}"
            )
        elif seg.kind == "screengrab":
            # operator-supplied capture — image (pad-fit) or short clip
            visual = content.resolve_screengrab(value)
            if visual.is_video:
                inputs += ["-i", str(visual.path)]
                chain = _clip_chain(i)
            else:
                inputs += ["-loop", "1", "-framerate", str(settings.fps),
                           "-t", f"{seg_len + 0.2:.4f}", "-i", str(visual.path)]
                chain = (f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                         f"{still_pad}{tail}")
        elif seg.kind in ("img", "chart", "asset", "meme"):
            if seg.kind == "img":
                visual = content.resolve_image(
                    value, kind="img", website=website,
                    choice=overrides.get(value, 0),
                )
            elif seg.kind == "chart":
                visual = content.resolve_chart(
                    value, ticker=script.ticker, company_data=company_data,
                    style=seg.payload.get("style", "clean"),
                )
            elif seg.kind == "asset":
                visual = content.resolve_asset(value)
            else:
                visual = content.resolve_meme(value)
            inputs += ["-loop", "1", "-framerate", str(settings.fps),
                       "-t", f"{seg_len + 0.2:.4f}", "-i", str(visual.path)]
            if seg.kind == "img":
                # slow punch-in drift so real imagery never sits static
                chain = (
                    f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                    f"scale={int(W * 1.08) // 2 * 2}:-2,"
                    f"crop={W}:{H}:x='(iw-ow)*t/{max(seg_len, 0.1):.4f}':y='(ih-oh)/2'"
                    f"{tail}"
                )
            else:
                chain = (
                    f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                    f"{still_pad}{tail}"
                )
        else:  # filler
            visual = None
            look = _FILLER_LOOKS[seg.payload.get("variant", 0) % len(_FILLER_LOOKS)].format(W=W, H=H)
            inputs += ["-loop", "1", "-framerate", str(settings.fps),
                       "-t", f"{seg_len + 0.2:.4f}", "-i", str(filler_bg)]
            chain = (
                f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H},{look}{tail}"
            )
        meta = {"kind": seg.kind, "start": seg.start, "end": seg.end}
        if value:
            meta["value"] = value
        if visual is not None:
            meta["source"] = visual.source
            meta["attribution"] = visual.attribution
        else:
            meta["attribution"] = ""
        if seg.kind == "filler":
            meta["variant"] = seg.payload.get("variant", 0)
        seg_meta.append(meta)
        lines.append(chain)

    concat_in = "".join(f"[s{i}]" for i in range(len(segments)))
    lines.append(f"{concat_in}concat=n={len(segments)}:v=1:a=0[vcat]")
    lines.append(f"[vcat]fps={settings.fps}[v0]")

    # ------------------------------------------------------------ layers
    layers: list[OverlayLayer] = []
    px = lambda v: int(round(v * W / 1920))  # noqa: E731  (1920-wide design)

    # glitch flash on every filing reveal (pre-rendered overlay)
    glitch = settings.assets_dir / "overlays" / "glitch_noise.mov"
    if glitch.exists():
        glitch_big = rdir / "glitch_scaled.mov"
        if not glitch_big.exists():
            run_ffmpeg(["-i", str(glitch),
                        "-vf", f"scale={W}:{H}:flags=neighbor",
                        "-c:v", "png", "-pix_fmt", "rgba", str(glitch_big)])
        for seg in segments:
            if seg.kind == "filing":
                layers.append(OverlayLayer(
                    path=glitch_big, x=0, y=0,
                    t_start=seg.start, t_end=min(seg.start + 0.5, duration),
                    is_video=True, name=f"glitch@{seg.start:.2f}",
                ))

    # hand-drawn overlays (TOP layer, riding over whatever segment shows):
    # [DOODLE] boils in a corner, [SCRIBBLE] draws a mark + target callout
    doodle_slots = [(px(1180), px(140)), (px(120), px(150)),
                    (px(1180), px(560)), (px(120), px(560))]
    for k, c in enumerate(doodle_cues):
        visual = content.resolve_doodle(c.payload["value"])
        if visual is None:
            log.warning("doodle %r not resolved — skipped", c.payload["value"])
            continue
        hold = float(c.payload.get("hold", 2.0))
        clip, (cw, ch) = doodle_clip(
            visual.path, rdir / f"doodle_{k}.mov",
            display_w=px(520), duration_s=hold + 0.2, fps=settings.fps,
            seed=f"{script.ticker}|doodle|{k}",
        )
        sx, sy = doodle_slots[k % len(doodle_slots)]
        layers.append(OverlayLayer(
            path=clip, x=min(sx, W - cw), y=min(sy, H - ch),
            t_start=c.t, t_end=min(c.t + hold, duration),
            is_video=True, name=f"doodle_{k}_{visual.key[:16]}",
        ))
    for k, c in enumerate(scribble_cues):
        parsed = parse_scribble_payload(c.payload["value"])
        if parsed is None:
            continue
        style, target = parsed
        hold = float(c.payload.get("hold", 2.0))
        sw, sh = px(700), px(460)
        frames = scribble_callout_frames(
            settings, sw, sh, style=style.value, target=target,
            fps=settings.fps, hold_seconds=hold, seed=f"{script.ticker}|scr|{k}",
        )
        clip = frames_to_alpha_clip(frames, settings.fps, rdir / f"scribble_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=int((W - sw) / 2), y=int((H - sh) / 2),
            t_start=c.t, t_end=min(c.t + hold + 0.5, duration),
            is_video=True, hold=True, name=f"scribble_{k}",
        ))

    # corner bug: ticker + as-of date (the as-of stays visible; no "audit")
    bug_text = script.ticker + (f" · as of {as_of}" if as_of else "")
    bug = simple_text(settings, bug_text, font_size=px(34),
                      fill=(255, 255, 255, 200), stroke_width=2)
    bug_path = rdir / "corner_bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=W - bug.width - px(36), y=px(30),
        t_start=0.0, t_end=duration, name="corner_bug",
    ))

    # branded lower-third: ticker + the channel tagline (persistent, bottom-left)
    lt = lower_third(settings, f"${script.ticker}", settings.brand_tagline.lower(),
                     width=px(560), font_size=px(34))
    lt_path = rdir / "lower_third.png"
    lt.save(lt_path)
    layers.append(OverlayLayer(
        path=lt_path, x=px(36), y=H - lt.height - px(92),
        t_start=0.0, t_end=duration, name="lower_third",
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
    # kept narrow (max ~22 chars) so a 9:16 center crop (repurpose)
    # retains them fully
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_karaoke_ass(
        tts.words, play_res=(W, H), font_size=px(52), margin_v=px(84),
        max_words=4, max_chars=22, duration=duration,
    ))

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, gain_db=0.0)]
    music = settings.assets_dir / "music" / "dennis_bed.m4a"
    if music.exists():
        audio.append(AudioTrack(path=music, gain_db=settings.music_gain_db, loop=True))
    for c in cues:
        if c.kind is CueKind.SOUND and c.payload.get("value") in SFX_KEYS:
            sfx = settings.assets_dir / "sfx" / f"{c.payload['value']}.wav"
            if sfx.exists():
                audio.append(AudioTrack(path=sfx, start_s=c.t, gain_db=settings.sfx_gain_db))
    # meme stings: boom on every meme; the FIRST meme gets the occasional
    # record-scratch rewind treatment
    boom = settings.assets_dir / "sfx" / "vine_boom.wav"
    scratch = settings.assets_dir / "sfx" / "record_scratch.wav"
    meme_segs = [s for s in segments if s.kind == "meme"]
    for j, seg in enumerate(meme_segs):
        if boom.exists():
            audio.append(AudioTrack(path=boom, start_s=seg.start,
                                    gain_db=settings.sfx_gain_db + 2))
        if j == 0 and scratch.exists():
            audio.append(AudioTrack(path=scratch,
                                    start_s=max(seg.start - 0.35, 0.0),
                                    gain_db=settings.sfx_gain_db))

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
