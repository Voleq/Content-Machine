"""LONG host-anchored engine — 16:9 deadpan deep-dive (§5).

Structure:
  * clean audio from the tag-stripped narration (cached TTS)
  * `build_long_timeline` resolves every tag to its spoken word
  * `plan_long_segments` tiles the full duration with host beats and the
    evidence he cuts away to
  * the whole video is ONE ffmpeg filter_complex: per-segment trim ->
    concat -> bug/disclaimer/glitch overlays -> libass captions, plus
    VO + music bed + SFX in a single amix — one final encode
  * draft mode reuses the same cached audio and graph at low res /
    ultrafast (never re-calls TTS)

DENNIS IS THE BASE FRAME (§editing): this is a talking-host show. Untagged
narration is the host on screen, lip-synced to the voice-over by
`pipeline.host`; a tag means leave his face for a piece of evidence and hold
it long enough to read. Nothing flashes by: data visuals cannot be cut short
by a later tag, that tag is deferred instead. Doodles/scribbles ride ON TOP,
including over the host.

Segment kinds:
  host    Dennis talking — the default frame, one held beat per untagged gap
  clip    ironic stock footage (content engine, palette-first), real motion
  img     real operations/product imagery, full-frame + Ken Burns
  meme    freeze-frame from the owned library, composed full-frame + boom
          (first one gets the record-scratch rewind)
  chart   auto-generated channel-style chart — a TWO-SHOT beside the host
  filing  the unnamed-source data screenshot, glitch flash on reveal
  asset   bespoke Claude-Design visual from assets/custom/ — also a two-shot

Layouts: host-full (him alone), two-shot (him beside a designed panel) and
cutaway-full (raw full-frame photography, footage and filings), always
returning to him. Chapter boundaries reserve a host beat on each side, so a
chapter opens and closes on his face.

Chapter stingers divide the acts; the branded strip + corner bug frame the
top, captions sit in a fitted box band clear of the furniture. Every visual
lands on its anchor word (or the first moment after it that is free); there
is no verdict stamp — the video ends on whatever deadpan line the script
wrote.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import Settings
from pipeline.broll import ContentManager
from pipeline.company_data import prepare_screenshot
from pipeline.host import build_host_clip
from pipeline.kit import load_kit
from pipeline.models import (
    CueKind,
    KIT_TAG_FAMILIES,
    LongScript,
    SFX_KEYS,
    TagType,
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
    chapter_start_times,
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


# Segment kinds a viewer READS. The old engine moved every still because
# nothing else on screen moved; now Dennis carries the motion, and drifting
# a table or a chart under someone's eyes is just harder to read. These hold
# dead still — which also removes zoompan, far and away the most expensive
# filter in the graph, from the majority of segments.
_STILL_KINDS = frozenset({
    "chart", "filing", "screengrab", "asset", "table", "term", "bignum",
})


def _hold_still_chain(i: int, seg_len: float, W: int, H: int, tail: str) -> str:
    """A still, held: contain-fit onto the paper, no movement at all."""
    return (
        f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xF2F2EF{tail}"
    )


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
    preview: bool = False,
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
        chapter_starts=chapter_start_times(script.chapters, duration),
        min_readable_s=settings.long_min_readable_s,
        chapter_host_s=settings.long_chapter_host_s,
    )
    for w in seg_warnings:
        log.warning("segment plan: %s", w)

    # Three tiers. PREVIEW is for judging the edit — 480p at half the frame
    # rate, where the filter graph (not the encode) is the cost. DRAFT is the
    # half-res review copy. Neither ever re-calls TTS.
    FW, FH = settings.long_resolution          # full spec
    scale = (settings.preview_scale if preview
             else settings.draft_scale if draft else 1.0)
    W = int(FW * scale) // 2 * 2
    H = int(FH * scale) // 2 * 2
    fps = settings.preview_fps if preview else settings.fps

    rdir = workspace / ("render_long_preview" if preview
                        else "render_long_draft" if draft else "render_long")
    rdir.mkdir(parents=True, exist_ok=True)

    website = str(company_data.get("website") or "") if company_data is not None else ""
    overrides = broll_overrides or {}
    kit = load_kit(settings.assets_dir)

    px = lambda v: int(round(v * W / 1920))  # noqa: E731  (1920-wide design)

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

    def _still_chain(input_i: int, seg, seg_len: float, seg_i: int,
                     tail: str) -> str:
        """Motion for a still segment: held dead still when the viewer has
        to read it, a gentle Ken Burns drift when it is only atmosphere."""
        if seg.kind in _STILL_KINDS:
            return _hold_still_chain(input_i, seg_len, W, H, tail)
        return _ken_burns_chain(input_i, seg_len, W, H, _kb_mode(seg_i), tail,
                                fps)

    # ------------------------------------------------------- the host rig
    # Dennis is composited per segment, lip-synced to that segment's slice of
    # the voice-over. `HOST_POSES` rotate with the beat index so a long cut
    # never returns to an identical shot; a missing rig degrades to the
    # designed backdrop rather than failing the render.
    host_h = int(H * 0.82)

    def _host_input(seg_i: int, seg, seg_len: float, *, panel: bool = False):
        """Add the host clip as an input. Returns (index, x, y) or None."""
        side = seg.payload.get("host_side", "left")
        if panel:
            # in a two-shot he faces the panel on the other side
            facing = "right" if side == "left" else "left"
            expression = "point"
        else:
            facing = "right" if seg_i % 2 == 0 else "left"
            expression = "talk"
        built = build_host_clip(
            tts.words, seg.start, seg.end, rdir / f"host_{seg_i}.mov",
            display_h=host_h, fps=fps,
            expression=expression, facing=facing, root=settings.assets_dir.parent,
        )
        if built is None:
            return None
        clip_path, (hw, hh) = built
        if panel:
            x = px(60) if side == "left" else W - hw - px(60)
        else:
            x = int((W - hw) / 2)
        return _add_input(["-i", str(clip_path)]), x, H - hh

    def _overlay_chain(bg_i: int, fg_i: int, x: int, y: int,
                       seg_len: float, seg_i: int, tail: str) -> str:
        """Backdrop + alpha host clip -> one concat-ready segment stream."""
        return (
            f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}[hbg{seg_i}];"
            f"[{fg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
            f"trim=0:{seg_len:.4f}[hfg{seg_i}];"
            f"[hbg{seg_i}][hfg{seg_i}]overlay={x}:{y}:eof_action=repeat"
            f"{tail}"
        )

    def _panel_frame(still: Path, host_side: str, dest: Path, *, variant: int) -> Path:
        """The two-shot plate: the designed panel inset on the side opposite
        Dennis, over the room backdrop."""
        from PIL import Image

        base = Image.open(_backdrop_path(variant)).convert("RGB").resize((W, H))
        panel = Image.open(still).convert("RGBA")
        max_w, max_h = int(W * 0.56), int(H * 0.72)
        ratio = min(max_w / panel.width, max_h / panel.height)
        panel = panel.resize((max(int(panel.width * ratio), 1),
                              max(int(panel.height * ratio), 1)), Image.LANCZOS)
        x = W - panel.width - px(70) if host_side == "left" else px(70)
        base.paste(panel, (x, int((H - panel.height) / 2)), panel)
        base.save(dest)
        return dest

    shot_cache: dict[str, Path] = {}
    meme_frame_cache: dict[str, Path] = {}
    # A host beat needs two inputs (the room, then Dennis over it), so input
    # indices are tracked explicitly rather than assumed equal to the segment
    # index.
    n_inputs = 0

    def _add_input(args: list[str]) -> int:
        nonlocal n_inputs
        inputs.extend(args)
        n_inputs += 1
        return n_inputs - 1

    for i, seg in enumerate(segments):
        seg_len = seg.length
        # every chain ends with setsar=1 AFTER the move — a crop/scale look
        # would otherwise re-derive a non-1:1 SAR and make the concat filter
        # reject the stream
        tail = f",setsar=1,format=yuv420p[s{i}]"
        value = seg.payload.get("value", "")

        def _still_input(path: Path) -> int:
            return _add_input(["-loop", "1", "-framerate", str(fps),
                               "-t", f"{seg_len + 0.2:.4f}", "-i", str(path)])

        def _clip_motion(idx: int) -> str:
            # real footage motion, cover-scaled, with a gentle drift so even a
            # short clone-padded clip keeps moving
            return (
                f"[{idx}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},scale={W}:{H}{tail}"
            )

        if seg.kind == "host":
            # Dennis is the default base frame: the room, then the talking rig
            # lip-synced to this segment's slice of the voice-over.
            visual = None
            variant = seg.payload.get("variant", 0)
            bg_i = _still_input(_backdrop_path(variant))
            host = _host_input(i, seg, seg_len)
            if host is None:
                chain = _still_chain(bg_i, seg, seg_len, i, tail)
            else:
                host_i, hx, hy = host
                chain = _overlay_chain(bg_i, host_i, hx, hy, seg_len, i, tail)
        elif seg.kind == "clip":
            visual = content.resolve_clip(value, overrides.get(value, 0))
            clip_i = _add_input(["-i", str(visual.path)])
            chain = _clip_motion(clip_i)
        elif seg.kind == "filing":
            if value not in shot_cache:
                shot_cache[value] = prepare_screenshot(
                    workspace / value, rdir / f"shot_{Path(value).stem}.png", settings
                )
            visual = None
            still_i = _still_input(shot_cache[value])
            chain = _still_chain(still_i, seg, seg_len, i, tail)
        elif seg.kind == "screengrab":
            # operator-supplied capture — image (full-frame) or short clip
            visual = content.resolve_screengrab(value)
            if visual.is_video:
                clip_i = _add_input(["-i", str(visual.path)])
                chain = _clip_motion(clip_i)
            else:
                still_i = _still_input(visual.path)
                chain = _still_chain(still_i, seg, seg_len, i, tail)
        elif seg.kind in ("term", "bignum", "table", "prop"):
            # owned design-kit artwork, addressed by name through the registry
            visual = None
            family = KIT_TAG_FAMILIES[TagType(seg.kind.upper())]
            still = kit.resolve(family, value)
            if still is None:
                log.warning("kit asset %s/%s missing — designed backdrop instead",
                            family, value)
                still = _backdrop_path(seg.payload.get("variant", i))
            host = (_host_input(i, seg, seg_len, panel=True)
                    if seg.payload.get("layout") == "two-shot" else None)
            if host is None:
                still_i = _still_input(still)
                chain = _still_chain(still_i, seg, seg_len, i, tail)
            else:
                panel = _panel_frame(still, seg.payload.get("host_side", "left"),
                                     rdir / f"panel_{i}.png", variant=i)
                bg_i = _still_input(panel)
                host_i, hx, hy = host
                chain = _overlay_chain(bg_i, host_i, hx, hy, seg_len, i, tail)
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
            # A designed panel (chart / bespoke diagram) plays as a TWO-SHOT:
            # Dennis stays in frame beside it, so the cut never leaves the
            # host. Photographs, footage and memes stay raw and full-frame.
            host = (_host_input(i, seg, seg_len, panel=True)
                    if seg.payload.get("layout") == "two-shot" else None)
            if host is None:
                still_i = _still_input(still)
                chain = _still_chain(still_i, seg, seg_len, i, tail)
            else:
                panel = _panel_frame(still, seg.payload.get("host_side", "left"),
                                     rdir / f"panel_{i}.png", variant=i)
                bg_i = _still_input(panel)
                host_i, hx, hy = host
                chain = _overlay_chain(bg_i, host_i, hx, hy, seg_len, i, tail)
        else:  # an unrecognised kind still gets a designed backdrop
            visual = None
            variant = seg.payload.get("variant", 0)
            still_i = _still_input(_backdrop_path(variant))
            chain = _still_chain(still_i, seg, seg_len, i, tail)
        meta = {"kind": seg.kind, "start": seg.start, "end": seg.end}
        if value:
            meta["value"] = value
        if visual is not None:
            meta["source"] = visual.source
            meta["attribution"] = visual.attribution
        else:
            meta["attribution"] = ""
        if seg.kind == "host":
            meta["variant"] = seg.payload.get("variant", 0)
        if seg.payload.get("layout"):
            meta["layout"] = seg.payload["layout"]
        seg_meta.append(meta)
        lines.append(chain)

    concat_in = "".join(f"[s{i}]" for i in range(len(segments)))
    lines.append(f"{concat_in}concat=n={len(segments)}:v=1:a=0[vcat]")
    lines.append(f"[vcat]fps={fps}[v0]")

    # ------------------------------------------------------------ layers
    layers: list[OverlayLayer] = []

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
    prev_doodle_key: str | None = None
    for k, c in enumerate(doodle_cues):
        visual = content.resolve_doodle(c.payload["value"])
        if visual is None:
            log.warning("doodle %r not resolved — skipped", c.payload["value"])
            continue
        # the same doodle can't ride two beats in a row (§variety) — a repeat
        # reads as a stuck frame; drop the adjacent duplicate
        if visual.key == prev_doodle_key:
            log.warning("doodle %r repeats back-to-back — skipped", visual.key)
            continue
        prev_doodle_key = visual.key
        hold = float(c.payload.get("hold", 2.0))
        clip, (cw, ch) = doodle_clip(
            visual.path, rdir / f"doodle_{k}.mov",
            display_w=px(520), duration_s=hold + 0.2, fps=fps,
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
            fps=fps, hold_seconds=hold, seed=f"{script.ticker}|scr|{k}",
        )
        clip = frames_to_alpha_clip(frames, fps, rdir / f"scribble_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=int((W - sw) / 2), y=int((H - sh) / 2),
            t_start=c.t, t_end=min(c.t + hold + 0.5, duration),
            is_video=True, hold=True, name=f"scribble_{k}",
        ))

    # corner bug: ticker + as-of date (top-right; the as-of stays visible)
    bug_text = script.ticker + (f" · as of {as_of}" if as_of else "")
    bug = simple_text(settings, bug_text, font_size=px(34),
                      fill=(35, 35, 38, 220), stroke_width=0)
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
                       fill=(143, 140, 131, 235), stroke_width=0)
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
    audio = [AudioTrack(path=tts.audio_path, gain_db=0.0, voice=True)]
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
        fps=fps,
    )
    out_path = workspace / ("long_draft.mp4" if draft else "long_final.mp4")
    profile = encode_profile(settings, "long", draft=draft, preview=preview)
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
