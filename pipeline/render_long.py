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

MEDIA IS THE BACKGROUND (§editing): every segment is a full-frame visual
with real motion — nothing is a static hold, nothing is a bare black frame.
Stills are composed to fill the frame (cover-fit / blurred-fill) and get a
randomized Ken Burns move; clips play their footage. Doodles/scribbles ride
ON TOP as brief overlay cutaways, never as the main element of a held frame.

Segment kinds:
  clip    ironic stock footage (content engine, palette-first), real motion
  img     real operations/product imagery, full-frame + Ken Burns
  meme    freeze-frame from the owned library, composed full-frame + boom
          (first one gets the record-scratch rewind)
  chart   auto-generated channel-style chart, Ken Burns
  filing  the unnamed-source data screenshot, glitch flash on reveal
  asset   bespoke Claude-Design visual from assets/custom/
  filler  a DESIGNED Dennis-palette backdrop (gradient / grid / signal card /
          chapter word / dot field), families spread so no two adjacent
          fillers share a look — never a bare black frame

Chapter stingers divide the acts; the branded strip + corner bug frame the
top, captions sit in a fitted box band clear of the furniture. Every visual
lands exactly on its anchor word; there is no verdict stamp — the video ends
on whatever deadpan line the script wrote.
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
    chapter_stinger,
    cover_fill_frame,
    doodle_clip,
    frames_to_alpha_clip,
    intro_card,
    long_backdrop,
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
from pipeline.timeline import (
    LONG_FILLER_LOOKS,
    build_long_timeline,
    plan_long_segments,
)

log = logging.getLogger(__name__)

# Ken Burns move vocabulary — every still gets one (randomized per segment)
# so nothing is a static hold. Pans ride a 1.14x upscale; zooms animate the
# crop window then rescale. All keep the WxH aspect exactly.
_KB_MODES = ("in", "out", "left", "right", "up", "down")

# chapter stinger titles (the LONG's designed section dividers) — rotated
# across the runtime at act boundaries
_CHAPTERS = [
    ("01", "the setup"),
    ("02", "what they do"),
    ("03", "the numbers"),
    ("04", "the industry"),
    ("05", "bull vs bear"),
    ("06", "the close"),
]


def _ken_burns_chain(i: int, seg_len: float, W: int, H: int, mode: str,
                     tail: str, fps: int) -> str:
    """A single still -> a moving WxH stream: input `[i:v]` upscaled 1.14x
    then panned (time-varying crop x/y) or zoomed (`zoompan`) over `seg_len`,
    ending in `tail` ([s{i}]). ffmpeg's `crop` only re-evaluates x/y per
    frame, so zoom rides zoompan rather than an animated crop window."""
    dur = max(seg_len, 0.1)
    zw = int(W * 1.14) // 2 * 2
    head = (f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,scale={zw}:-2,")
    if mode in ("in", "out"):
        n = max(int(round(dur * fps)), 2)
        if mode == "in":       # 1.00 -> 1.14
            z = f"min(1.0+0.14*on/{n},1.14)"
        else:                  # 1.14 -> 1.00
            z = f"max(1.14-0.14*on/{n},1.0)"
        body = (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={W}x{H}:fps={fps}")
        return f"{head}{body}{tail}"
    if mode == "right":
        xy = f"x='(iw-ow)*t/{dur:.4f}':y='(ih-oh)/2'"
    elif mode == "left":
        xy = f"x='(iw-ow)*(1-t/{dur:.4f})':y='(ih-oh)/2'"
    elif mode == "down":
        xy = f"x='(iw-ow)/2':y='(ih-oh)*t/{dur:.4f}'"
    else:  # "up"
        xy = f"x='(iw-ow)/2':y='(ih-oh)*(1-t/{dur:.4f})'"
    return f"{head}crop={W}:{H}:{xy}{tail}"


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

    # designed filler backdrops — the LONG's no-media fallback is a DESIGNED
    # Dennis-palette frame, never a bare black one. The variety planner numbers
    # fillers sequentially; here that index spreads across a POOL of distinct
    # designed cards (each backdrop family drawn with several seeds), drawn
    # once and cached, so a run of fillers reads as motion through a deck and
    # no two adjacent fillers ever share a look.
    backdrop_cache: dict[int, Path] = {}

    def _backdrop_path(variant: int) -> Path:
        slot = variant % LONG_FILLER_LOOKS
        if slot not in backdrop_cache:
            bp = rdir / f"backdrop_{slot}.png"
            if not bp.exists():
                _, chap = _CHAPTERS[slot % len(_CHAPTERS)]
                long_backdrop(settings, W, H, slot, ticker=script.ticker,
                              label=chap, seed=f"{script.ticker}|bg").save(bp)
            backdrop_cache[slot] = bp
        return backdrop_cache[slot]

    # deterministic per-render Ken Burns phase so the move sequence differs
    # per ticker but adjacent stills never share a direction
    kb_off = int(json.dumps(script.ticker).encode().hex()[:6], 16) if script.ticker else 0

    def _kb_mode(idx: int) -> str:
        return _KB_MODES[(idx + kb_off) % len(_KB_MODES)]

    shot_cache: dict[str, Path] = {}
    meme_frame_cache: dict[str, Path] = {}

    for i, seg in enumerate(segments):
        seg_len = seg.length
        # every chain ends with setsar=1 AFTER the move — a crop/scale look
        # would otherwise re-derive a non-1:1 SAR and make the concat filter
        # reject the stream
        tail = f",setsar=1,format=yuv420p[s{i}]"
        value = seg.payload.get("value", "")

        def _still_input(path: Path) -> None:
            inputs.extend(["-loop", "1", "-framerate", str(settings.fps),
                           "-t", f"{seg_len + 0.2:.4f}", "-i", str(path)])

        def _clip_motion(idx: int) -> str:
            # real footage motion, cover-scaled, with a gentle drift so even a
            # short clone-padded clip keeps moving
            return (
                f"[{idx}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},scale={W}:{H}{tail}"
            )

        if seg.kind == "clip":
            visual = content.resolve_clip(value, overrides.get(value, 0))
            inputs += ["-i", str(visual.path)]
            chain = _clip_motion(i)
        elif seg.kind == "filing":
            if value not in shot_cache:
                shot_cache[value] = prepare_screenshot(
                    workspace / value, rdir / f"shot_{Path(value).stem}.png", settings
                )
            visual = None
            _still_input(shot_cache[value])
            chain = _ken_burns_chain(i, seg_len, W, H, _kb_mode(i), tail, settings.fps)
        elif seg.kind == "screengrab":
            # operator-supplied capture — image (full-frame) or short clip
            visual = content.resolve_screengrab(value)
            if visual.is_video:
                inputs += ["-i", str(visual.path)]
                chain = _clip_motion(i)
            else:
                _still_input(visual.path)
                chain = _ken_burns_chain(i, seg_len, W, H, _kb_mode(i), tail, settings.fps)
        elif seg.kind in ("img", "chart", "asset", "meme"):
            if seg.kind == "img":
                visual = content.resolve_image(
                    value, kind="img", website=website,
                    choice=overrides.get(value, 0),
                )
                still = visual.path
            elif seg.kind == "chart":
                visual = content.resolve_chart(
                    value, ticker=script.ticker, company_data=company_data,
                    style=seg.payload.get("style", "clean"),
                )
                still = visual.path
            elif seg.kind == "asset":
                visual = content.resolve_asset(value)
                still = visual.path
            else:  # meme — compose the freeze-frame full-frame so it never
                   # sits letterboxed on black, then Ken Burns over it
                visual = content.resolve_meme(value)
                if visual.key not in meme_frame_cache:
                    dest = rdir / f"meme_frame_{len(meme_frame_cache)}.png"
                    cover_fill_frame(visual.path, W, H, keep_min=1.1).save(dest)
                    meme_frame_cache[visual.key] = dest
                still = meme_frame_cache[visual.key]
            _still_input(still)
            chain = _ken_burns_chain(i, seg_len, W, H, _kb_mode(i), tail, settings.fps)
        else:  # filler -> a DESIGNED backdrop, Ken Burns
            visual = None
            variant = seg.payload.get("variant", 0)
            _still_input(_backdrop_path(variant))
            chain = _ken_burns_chain(i, seg_len, W, H, _kb_mode(i), tail, settings.fps)
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

    # composed opening title card (a real open, not a lone mascot on a flat
    # backdrop) — full-frame over the first beat, fading out on its own
    scenes_dir = settings.assets_dir / "brand" / "scenes"
    intro_scene = scenes_dir / "at-the-desk-the-setup.png"
    intro_dur = min(2.6, duration * 0.5)
    intro_path = rdir / "intro_card.png"
    intro_card(settings, script.ticker, settings.brand_tagline.lower(),
               width=W, height=H,
               scene_path=intro_scene if intro_scene.exists() else None).save(intro_path)
    layers.append(OverlayLayer(
        path=intro_path, x=0, y=0, t_start=0.0, t_end=intro_dur, name="intro_card",
    ))

    # chapter stingers — the design system's section dividers, landing on a
    # real cut near each act boundary, brief with a fade (the intro covers
    # act one, so these run from act two)
    seg_starts = [s.start for s in segments]
    n_ch = len(_CHAPTERS)
    used_ch: set[float] = set()
    for k in range(1, n_ch):
        target = duration * k / n_ch
        t = next((s for s in seg_starts
                  if s >= max(target, intro_dur) and s not in used_ch), None)
        if t is None or t < 0.6 or t > duration - 1.2:
            continue
        used_ch.add(t)
        num, title = _CHAPTERS[k]
        cs_path = rdir / f"chapter_{k}.png"
        if not cs_path.exists():
            chapter_stinger(settings, num, title, width=W, height=H).save(cs_path)
        layers.append(OverlayLayer(
            path=cs_path, x=0, y=0, t_start=t, t_end=min(t + 0.9, duration),
            fade_in=0.2, name=f"chapter_{k}",
        ))

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

    # corner bug: ticker + as-of date (top-right; the as-of stays visible)
    bug_text = script.ticker + (f" · as of {as_of}" if as_of else "")
    bug = simple_text(settings, bug_text, font_size=px(34),
                      fill=(255, 255, 255, 200), stroke_width=2)
    bug_path = rdir / "corner_bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=W - bug.width - px(36), y=px(30),
        t_start=0.0, t_end=duration, name="corner_bug",
    ))

    # branded strip: ticker + channel tagline. Persistent, TOP-left — moved
    # off the bottom so it can never clip or stack with the caption band.
    lt = lower_third(settings, f"${script.ticker}", settings.brand_tagline.lower(),
                     width=px(560), font_size=px(34))
    lt_path = rdir / "lower_third.png"
    lt.save(lt_path)
    layers.append(OverlayLayer(
        path=lt_path, x=px(36), y=px(30),
        t_start=0.0, t_end=duration, name="lower_third",
    ))

    disc = simple_text(settings, settings.disclaimer_text, font_size=px(26),
                       fill=(235, 235, 235, 190), stroke_width=2)
    disc_path = rdir / "disclaimer.png"
    disc.save(disc_path)
    layers.append(OverlayLayer(
        path=disc_path, x=px(36), y=H - px(44),
        t_start=0.0, t_end=duration, name="disclaimer",
    ))

    # ---------------------------------------------------------- captions
    # A fitted opaque box per line (box=True) sized to its own text, sitting
    # in a dedicated bottom band CLEAR of the disclaimer and the top strip —
    # so a LONG caption line ("...three a.m., again...") can never clip
    # off-frame or overlap the furniture. Kept narrow so a 9:16 centre crop
    # (repurpose) retains it.
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_karaoke_ass(
        tts.words, play_res=(W, H), font_size=px(50), margin_v=px(150),
        max_words=4, max_chars=24, duration=duration, box=True,
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
        "layers": [
            {"name": l.name, "t_start": l.t_start, "t_end": l.t_end,
             "x": l.x, "y": l.y}
            for l in layers
        ],
        "segment_warnings": seg_warnings,
        "attributions": attributions,
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2))
    return out_path, manifest_path
