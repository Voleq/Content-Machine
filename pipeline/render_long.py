"""LONG host-anchored engine — 16:9 deadpan deep-dive (§5).

Structure:
  * clean audio from the tag-stripped narration (cached TTS)
  * `build_long_timeline` resolves every tag to its spoken word
  * `plan_long_segments` tiles the full duration with host beats and the
    evidence he cuts away to
  * the whole video is ONE ffmpeg filter_complex: per-segment trim ->
    concat -> bug/disclaimer/glitch overlays -> libass captions, plus
    VO + music bed + SFX in a single amix — one final encode

NOTHING PANS OR ZOOMS. Motion is the host (mouth flap, boil pairs), the cuts,
and real video clips. Every still is scale + pad, held.
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
  img     real operations/product imagery, full-frame and held still
  meme    freeze-frame from the owned library, composed full-frame + boom
          (first one gets the record-scratch rewind)
  chart   auto-generated channel-style chart — a TWO-SHOT beside the host
  filing  the unnamed-source data screenshot, glitch flash on reveal
  asset   bespoke Claude-Design visual from assets/custom/ — also a two-shot

Layouts: host-full (him alone), two-shot (him beside a designed panel) and
cutaway-full (raw full-frame photography, footage and filings), always
returning to him. Chapter boundaries reserve a host beat on each side, so a
chapter opens and closes on his face.

ONE COMPOSITION PER FRAME. The host shots are complete 16:9 scenes — Dennis,
a headline, often an illustration of their own — so a host beat IS the frame
and nothing goes behind it. A two-shot is composed as a single still: paper,
the evidence, and a cut-out `mascot/` figure standing beside it. It used to
stack three finished designs (a designed backdrop with its own giant ticker,
an evidence card, and a whole host slide over both), which is what made the
cut read as a collage.

Kit artwork is addressed through the registry as an ASSET, not a path, so a
tag's `= value` reaches the drawing's declared boxes and a one-shot shows its
end state rather than freezing on frame 1.

Chapter stingers divide the acts; the branded strip + corner bug frame the
top, captions are the same phrase-by-phrase chips the short uses — dark ink
on paper, a whole clause at a time. Every visual lands on its anchor word (or
the first moment after it that is free); there is no verdict stamp — the
video ends on whatever deadpan line the script wrote.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable

from config import Settings
from pipeline.broll import ContentManager
from pipeline.company_data import prepare_screenshot
from pipeline.host import build_host_clip
from pipeline.kit import load_kit
from pipeline.kit_frames import (
    playback_seconds,
    render_clip,
    transition_asset,
    transition_transform,
)
from pipeline.models import (
    CueKind,
    KIT_TAG_BLANKS,
    KIT_TAG_FAMILIES,
    LongScript,
    SFX_KEYS,
    TagType,
    TTSResult,
    parse_scribble_payload,
)
from pipeline.rasters import (
    build_phrase_ass,
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
    render_thread_budget,
    run_ffmpeg,
)
from pipeline.segments import (
    CACHE_DIRNAME as SEG_CACHE_DIRNAME,
    SegmentRun,
    SegmentSpec,
    concat_clips,
    encode_segments,
)
from pipeline.timeline import (
    LONG_FILLER_LOOKS,
    build_long_timeline,
    chapter_start_times,
    plan_long_segments,
)

log = logging.getLogger(__name__)

# FALLBACK chapter titles, for a script whose `=== CHAPTERS ===` trailer is
# missing or unparseable. Not the source of truth: the writer's own trailer
# is, and this list used to override it. Every long video carried these six
# section titles spaced evenly across its runtime regardless of what its
# sections actually were, which is a caption that is simply wrong on screen.
# Using it is warned about.
_CHAPTERS = [
    ("01", "the setup"),
    ("02", "what they do"),
    ("03", "the numbers"),
    ("04", "the industry"),
    ("05", "bull vs bear"),
    ("06", "the close"),
]


def _chapter_plan(chapters: str, duration: float,
                  warn: Callable[[str], None]) -> list[tuple[float, str]]:
    """`(time, title)` for the stingers — the script's own, or the fallback.

    A chapter with a timestamp and no title still counts as a boundary; it
    borrows the fallback's wording rather than drawing a blank card.
    """
    from pipeline.timeline import chapter_start_times

    parsed = chapter_start_times(chapters, duration)
    if parsed:
        out: list[tuple[float, str]] = []
        for i, (t, title) in enumerate(parsed):
            if not title:
                warn(f"chapter at {t:.0f}s has a timestamp but no title — "
                     f"using the generic one")
                title = _CHAPTERS[i % len(_CHAPTERS)][1]
            out.append((t, title))
        return out

    warn("the script has no usable `=== CHAPTERS ===` trailer — the stingers "
         "fall back to generic section titles, which will not match the cut")
    n = len(_CHAPTERS)
    return [(duration * k / n, _CHAPTERS[k][1]) for k in range(1, n)]


# NOTHING PANS OR ZOOMS. Dennis carries the motion — the mouth flap, the boil
# pairs, the cuts and real video footage. Everything else holds dead still.
#
# The old engine drifted every still because nothing else on screen moved;
# once the host arrived that stopped being true, and a drifting frame is both
# harder to read and, via `zoompan`, by far the most expensive operation in
# the filter graph. Removing it outright makes every still segment a plain
# scale + pad — which is also what lets a segment be content-hashed and
# cached, since the output no longer depends on its position in the timeline.


_INPUT_LABEL_RE = re.compile(r"\[(\d+):v\]")


def _globalise(chain: str, offset: int, index: int) -> str:
    """A locally-indexed segment chain, re-numbered for the single graph.

    Segment chains are authored against local input indices and end in
    [out]; the monolithic path needs absolute indices and an [s{i}] label.
    Only `[N:v]` matches — the internal labels are named ([hbg], [hfg]), so
    they are never caught.
    """
    shifted = _INPUT_LABEL_RE.sub(lambda m: f"[{int(m.group(1)) + offset}:v]", chain)
    return shifted.replace("[hbg]", f"[hbg{index}]").replace("[hfg]", f"[hfg{index}]") \
                  .replace("[out]", f"[s{index}]")


def _segment_fallback(spec: SegmentSpec, backdrop_for, W: int, H: int,
                      fps: int) -> SegmentSpec | None:
    """What a failed segment becomes: the designed backdrop, held.

    One unresolvable asset should cost one beat, not the whole cut.
    """
    try:
        bg = backdrop_for(spec.index)
    except Exception:  # noqa: BLE001
        return None
    return SegmentSpec(
        index=spec.index, kind="host", duration=spec.duration,
        width=W, height=H, fps=fps,
        inputs=(("-loop", "1", "-framerate", str(fps),
                 "-t", f"{spec.duration + 0.2:.4f}", "-i", str(bg)),),
        filter_chain=_hold_still_chain(0, spec.duration, W, H,
                                       ",setsar=1,format=yuv420p[out]"),
        layout="host-full",
        extra_identity=("fallback",),
    )


def _hold_still_chain(i: int, seg_len: float, W: int, H: int, tail: str) -> str:
    """A still, held: contain-fit onto the paper, no movement at all."""
    return (
        f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xF2F2EF{tail}"
    )


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
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[Path, Path]:
    """Render the LONG (or its low-res draft). Returns (mp4, manifest)."""
    # Draft audio (the free local voice) has word timings that are exact per
    # sentence and interpolated within one. Good enough to judge pacing, not
    # good enough to be the master clock of something published — and the
    # whole pipeline trusts that clock. Enforced here rather than left to
    # discipline, because the failure is invisible: it renders fine, it is
    # just subtly out of sync.
    if not draft and getattr(tts, "draft", False):
        raise RenderError(
            f"refusing to make a FINAL render from {tts.tier} draft audio — "
            f"its word timings are interpolated inside each sentence. Approve "
            f"the script so the paid voice runs, then render.")
    content = content or ContentManager(settings)
    duration = tts.duration_s
    cues = build_long_timeline(script, tts.words, duration)
    doodle_cues = [c for c in cues if c.kind is CueKind.DOODLE]
    scribble_cues = [c for c in cues if c.kind is CueKind.SCRIBBLE]
    chapter_warnings: list[str] = []
    chapters = _chapter_plan(script.chapters, duration, chapter_warnings.append)
    for w in chapter_warnings:
        log.warning("chapters: %s", w)
    segments, seg_warnings = plan_long_segments(
        cues, duration,
        chapter_starts=chapters,
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

    def progress(done: int, total: int) -> None:
        log.info("segments %d/%d", done, total)
        if on_progress is not None:
            on_progress(done, total)

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
    backdrop_cache: dict[tuple[int, str], Path] = {}

    # A backdrop is labelled with the chapter it falls in, so the words on a
    # filler card belong to the section actually being narrated. Labelling
    # them off the same hardcoded six-entry list as the stingers meant a
    # filler in the valuation chapter could be captioned "the industry".
    chapter_labels = [title for _, title in chapters]

    def _backdrop_path(variant: int, at: float | None = None) -> Path:
        slot = variant % LONG_FILLER_LOOKS
        label = ""
        if chapter_labels:
            if at is None:
                label = chapter_labels[slot % len(chapter_labels)]
            else:
                label = next((ti for (ct, ti) in reversed(chapters) if at >= ct),
                             chapter_labels[0])
        key = (slot, label)
        if key not in backdrop_cache:
            bp = rdir / f"backdrop_{slot}_{abs(hash(label)) % 9973:04d}.png"
            if not bp.exists():
                long_backdrop(settings, W, H, slot, ticker=script.ticker,
                              label=label, seed=f"{script.ticker}|bg").save(bp)
            backdrop_cache[key] = bp
        return backdrop_cache[key]

    # ---------------------------------------------- kit artwork, rendered
    # Addressed by PATH before this, which meant the long cut got the raw
    # first frame of the PNG: 39 reachable drawings played with their declared
    # boxes empty, both blank layouts shipped the placeholder copy printed
    # into them ("What the word means"), and 22 one-shot strips froze on
    # frame 1 — a drawing of nothing having happened yet.
    # Every third eligible kit beat is framed tighter. Enough to break a
    # forty-minute rhythm of identically-fitted cards, rare enough to stay an
    # emphasis. Counted over ELIGIBLE beats, so it cannot fall out of phase.
    punch_cycle = [0]

    def _kit_art(seg, seg_i: int, value: str):
        """(path, is_video, (w, h), frame plan) for one kit beat.

        The long engine held every asset on frame 1 — 84 multi-frame drawings
        frozen, the 57 boil pairs never shimmering, every one-shot showing the
        moment before it happens. Everything here already existed in
        `kit_frames` and was exercised by the short; none of it was reachable
        from a long cut.
        """
        from pipeline.kit_frames import (
            bind_slot_values, frame_indices, is_full_frame, playback_seconds,
            punch_crop, render_clip, render_still, strip_baked_furniture,
        )

        tag = TagType(seg.kind.upper())
        family = KIT_TAG_FAMILIES[tag]
        asset = kit.resolve_asset(family, value)
        is_blank = False
        if asset is None:
            blank = KIT_TAG_BLANKS.get(tag)
            asset = kit.get(blank) if blank else None
            is_blank = asset is not None
        if asset is None:
            log.warning("kit asset %s/%s missing — designed backdrop instead",
                        family, value)
            bp = _backdrop_path(seg.payload.get("variant", seg_i),
                                seg.payload.get("at"))
            return bp, False, None, (), None

        if is_blank:
            values = _long_blank_values(tag, value, seg.payload.get("values"))
        else:
            values, slot_warnings = bind_slot_values(
                asset, seg.payload.get("values"))
            for w in slot_warnings:
                log.warning("slot: %s", w)

        # A card drawn to BE a 16:9 frame stays the frame; a drawing sits in
        # the evidence column, and every third one is cropped tighter. The
        # blank layouts are typeset, so they never punch.
        full = is_full_frame(asset, (W, H))
        croppable = not full and not any(s.clear for s in asset.slots)
        punch = False
        if croppable:
            punch_cycle[0] += 1
            punch = punch_cycle[0] % 3 == 0

        def shape(img):
            # The furniture comes off first. The long frame draws its own bug
            # and disclaimer, and the card's painted-in chip carries the design
            # file's placeholder ticker — `GYMX` sitting under our `$EXMPL`.
            img = strip_baked_furniture(img, asset)
            return punch_crop(img, asset) if punch else img

        if not asset.animated:
            dest = rdir / f"kit_{seg_i}_{asset.name[:24]}.png"
            img = shape(render_still(asset, values, settings)).convert("RGBA")
            img.save(dest)
            return dest, False, img.size, (), asset.key

        # Animated: the strip plays for the beat. A one-shot runs once and
        # holds its end frame; a boil pair shimmers; a loop cycles. The floor
        # is the strip's own length, so a six-frame transformation is never
        # cut half-drawn.
        span = max(seg.end - seg.start, playback_seconds(asset))
        plan = frame_indices(asset, span, fps)
        dest = rdir / f"kit_{seg_i}_{asset.name[:24]}.mov"
        clip, size = render_clip(
            asset, dest, duration_s=span, fps=fps, settings=settings,
            values=values, transform=shape,
        )
        return clip, True, size, tuple(plan), asset.key

    def _kit_still(seg, seg_i: int, value: str) -> Path:
        """Backwards-compatible still-only view of `_kit_art`."""
        return _kit_art(seg, seg_i, value)[0]

    def _long_blank_values(tag, key: str, values: dict | None) -> dict[str, str]:
        """Copy for a blank layout when the kit has no artwork for the key."""
        values = values or {}
        given = next((v for v in values.values() if v), "")
        label = key.replace("-", " ").strip()
        if tag is TagType.BIGNUM:
            return {"kicker": label, "figure": given or label,
                    "headline": "", "context": ""}
        return {"kicker": "the word of the day", "term": label.title(),
                "definition": given, "footnote": ""}

    def _still_chain(input_i: int, seg, seg_len: float, seg_i: int,
                     tail: str) -> str:
        """Every still is held. There is no drift on anything."""
        return _hold_still_chain(input_i, seg_len, W, H, tail)

    # ------------------------------------------------------- the host rig
    # Dennis is composited per segment, lip-synced to that segment's slice of
    # the voice-over. The shot steps through a bank with the beat index so a
    # long cut never returns to an identical frame; a kit that cannot supply
    # one degrades to the designed backdrop rather than failing the render.
    #
    # The rig moved with the kit: what used to be a pose assembled from mouth
    # frames is now a composed shot and its `-talk` twin, so `role` replaces
    # the old expression/facing pair. A two-shot asks for the `panel` bank —
    # the shots drawn with him beside something.
    # The host shots are COMPOSED 16:9 cards now, not the cut-out figure the
    # old rig assembled from mouth frames. Sizing them by height the way a
    # cut-out was sized made a 16:9 card 82% of the frame WIDTH, so in a
    # two-shot Dennis covered the panel he was supposed to be standing beside:
    # `Owner Earnings` rendered with four letters of its title showing.
    #
    # So: a host beat IS the frame, and a two-shot host takes the column the
    # panel leaves — the panel is 56% wide, he gets the rest.
    HOST_PANEL_W = 0.40

    def _host_input(seg_i: int, seg, seg_len: float, *, panel: bool = False):
        """Add the host clip as an input. Returns (index, x, y) or None."""
        side = seg.payload.get("host_side", "left")
        built = build_host_clip(
            tts.words, seg.start, seg.end, rdir / f"host_{seg_i}.mov",
            kit=kit, settings=settings, fps=fps,
            display_w=int(W * HOST_PANEL_W) if panel else W,
            role="panel" if panel else "beat", shot_index=seg_i,
            strip_furniture=True,
        )
        if built is None:
            return None
        clip_path, (hw, hh) = built
        if panel:
            x = px(60) if side == "left" else W - hw - px(60)
        else:
            x = int((W - hw) / 2)
        return _add_input(["-i", str(clip_path)]), x, max(H - hh, 0)

    def _overlay_chain(bg_i: int, fg_i: int, x: int, y: int,
                       seg_len: float, seg_i: int, tail: str) -> str:
        """Backdrop + alpha host clip -> one concat-ready segment stream."""
        return (
            f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}[hbg];"
            f"[{fg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
            f"trim=0:{seg_len:.4f}[hfg];"
            f"[hbg][hfg]overlay={x}:{y}:eof_action=repeat"
            f"{tail}"
        )

    def _scaled_overlay_chain(bg_i: int, fg_i: int, x: int, y: int,
                              w: int, h: int, seg_len: float, tail: str) -> str:
        """As `_overlay_chain`, but the strip is scaled into its column first.

        Kit strips are rendered at their own canvas size; the plate reserves a
        box for them, so the scale happens in the graph rather than by
        re-rendering every frame at the display size.
        """
        return (
            f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}[hbg];"
            f"[{fg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
            f"trim=0:{seg_len:.4f},scale={w}:{h}[hfg];"
            f"[hbg][hfg]overlay={x}:{y}:eof_action=repeat"
            f"{tail}"
        )

    def _two_shot_figure(variant: int):
        """The cut-out pose for a two-shot, already scaled. None when absent."""
        from PIL import Image

        from pipeline.host import panel_figure
        from pipeline.kit_frames import render_still, strip_baked_furniture

        figure = panel_figure(kit, variant)
        if figure is None:
            return None
        img = strip_baked_furniture(render_still(figure, None, settings), figure)
        fh = int(H * 0.62)
        fr = fh / max(img.height, 1)
        return img.resize((max(int(img.width * fr), 1), fh), Image.LANCZOS)

    def _evidence_box(fig_img, host_side: str) -> tuple[int, int, int]:
        """(max width, max height, the figure's x) for the evidence column."""
        fig_w = (fig_img.width + px(60)) if fig_img is not None else 0
        max_w = max(W - fig_w - px(150), px(400))
        fx = (px(70) if host_side == "left"
              else W - (fig_img.width if fig_img is not None else 0) - px(70))
        return max_w, int(H * 0.80), fx

    def _panel_plate(size: tuple[int, int], host_side: str, dest: Path, *,
                     variant: int, two_shot: bool) -> tuple[Path, int, int]:
        """Paper (and the figure) with a HOLE the evidence goes in.

        Returns (plate, x, y) — the origin an evidence image or clip of
        `size` should be composited at. Split out of `_panel_frame` so an
        animated beat can overlay its alpha strip on exactly the same
        composition a still gets pasted into.
        """
        from PIL import Image

        base = Image.new("RGB", (W, H), (242, 242, 239))
        fig_img = _two_shot_figure(variant) if two_shot else None
        _, _, fx = _evidence_box(fig_img, host_side)
        ew, eh = size
        if fig_img is None:
            ex = int((W - ew) / 2)
        elif host_side == "left":
            ex = W - ew - px(70)
        else:
            ex = px(70)
        ey = int((H - eh) / 2)
        if fig_img is not None:
            # Standing on the floor line, not floating mid-frame.
            base.paste(fig_img, (fx, H - fig_img.height - px(70)), fig_img)
        base.save(dest)
        return dest, ex, ey

    def _fit_evidence(w: int, h: int, host_side: str, *,
                      variant: int, two_shot: bool) -> tuple[int, int]:
        """The size an evidence image of (w, h) takes in its column."""
        fig_img = _two_shot_figure(variant) if two_shot else None
        max_w, max_h, _ = _evidence_box(fig_img, host_side)
        if not two_shot:
            max_w, max_h = int(W * 0.86), int(H * 0.86)
        ratio = min(max_w / max(w, 1), max_h / max(h, 1))
        return max(int(w * ratio), 1), max(int(h * ratio), 1)

    def _panel_frame(still: Path, host_side: str, dest: Path, *, variant: int,
                     two_shot: bool = True) -> Path:
        """The two-shot, as ONE composition: paper, the evidence, the figure.

        This used to be three finished designs stacked in one frame — a
        designed filler backdrop with its own giant ticker and grid, the
        evidence card on top of that, and a whole 16:9 host SLIDE pasted over
        both, carrying its own headline and often its own illustration. Every
        edge showed, the backdrop's watermark read through the line art, and
        two unrelated headlines argued with each other and with the caption.

        One background. One piece of evidence. One cut-out figure standing
        beside it, on the same sheet of paper.
        """
        from PIL import Image

        from pipeline.kit_frames import strip_baked_furniture

        # Any panel can be a long-form card carrying its own disclaimer — the
        # mock chart falls back to one — and the frame draws its own, so the
        # beat came out with the line printed twice. Signature-gated, so a
        # generated chart or a photograph is never touched.
        panel = strip_baked_furniture(Image.open(still).convert("RGBA"))
        ew, eh = _fit_evidence(panel.width, panel.height, host_side,
                               variant=variant, two_shot=two_shot)
        panel = panel.resize((ew, eh), Image.LANCZOS)
        plate, ex, ey = _panel_plate((ew, eh), host_side, dest,
                                     variant=variant, two_shot=two_shot)
        base = Image.open(plate).convert("RGB")
        base.paste(panel, (ex, ey), panel)
        base.save(dest)
        return dest

    shot_cache: dict[str, Path] = {}
    meme_frame_cache: dict[str, Path] = {}

    # Every segment's chain is built against LOCAL input indices (0, 1, …) and
    # ends in [out]. That is what a standalone per-segment encode needs, and
    # the single-graph fallback just re-numbers them (see `_globalise`).
    seg_specs: list[SegmentSpec] = []
    seg_inputs: list[list[str]] = []
    n_inputs = 0

    def _add_input(args: list[str]) -> int:
        nonlocal n_inputs
        seg_inputs.append(list(args))
        n_inputs += 1
        return n_inputs - 1

    for i, seg in enumerate(segments):
        seg_len = seg.length
        seg_inputs = []
        n_inputs = 0
        seg_animation: dict | None = None
        # setsar=1 AFTER the scale — a crop/scale would otherwise re-derive a
        # non-1:1 SAR and make the concat reject the stream
        tail = ",setsar=1,format=yuv420p[out]"
        value = seg.payload.get("value", "")

        def _still_input(path: Path) -> int:
            return _add_input(["-loop", "1", "-framerate", str(fps),
                               "-t", f"{seg_len + 0.2:.4f}", "-i", str(path)])

        def _clip_motion(idx: int) -> str:
            # Real footage carries its own motion, so it is simply cover-scaled
            # and clone-padded if the clip is shorter than the beat. No drift is
            # added — nothing in this pipeline pans or zooms.
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
            bg_i = _still_input(_backdrop_path(variant, seg.start))
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
            art, is_video, size, plan, key = _kit_art(seg, i, value)
            side = seg.payload.get("host_side", "left")
            two_shot = seg.payload.get("layout") == "two-shot"
            if is_video:
                # The strip is an alpha clip, so the plate it plays on is the
                # same composition a still gets pasted into.
                ew, eh = _fit_evidence(size[0], size[1], side,
                                       variant=i, two_shot=two_shot)
                plate, ex, ey = _panel_plate(
                    (ew, eh), side, rdir / f"plate_{i}.png",
                    variant=i, two_shot=two_shot)
                bg_i = _still_input(plate)
                fg_i = _add_input(["-i", str(art)])
                chain = _scaled_overlay_chain(bg_i, fg_i, ex, ey, ew, eh,
                                              seg_len, tail)
                seg_animation = {"asset": key, "frames": len(plan),
                                 "distinct": len(set(plan))}
            else:
                still = art
                # The two-shot is composed as ONE still — paper, evidence,
                # cut-out figure — rather than a host slide over a panel.
                still = _panel_frame(still, side, rdir / f"panel_{i}.png",
                                     variant=i, two_shot=two_shot)
                still_i = _still_input(still)
                chain = _still_chain(still_i, seg, seg_len, i, tail)
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
                   # sits letterboxed on black; it is then held still
                visual = content.resolve_meme(value)
                if visual.key not in meme_frame_cache:
                    dest = rdir / f"meme_frame_{len(meme_frame_cache)}.png"
                    cover_fill_frame(visual.path, W, H, keep_min=1.1).save(dest)
                    meme_frame_cache[visual.key] = dest
                still = meme_frame_cache[visual.key]
            # A designed panel (chart / bespoke diagram) plays as a TWO-SHOT:
            # Dennis stays in frame beside it, so the cut never leaves the
            # host. Photographs, footage and memes stay raw and full-frame.
            # The two-shot is composed as ONE still now — paper, evidence,
            # cut-out figure — rather than a host slide overlaid on a panel.
            if seg.payload.get("layout") == "two-shot":
                still = _panel_frame(still, seg.payload.get("host_side", "left"),
                                     rdir / f"panel_{i}.png", variant=i)
            still_i = _still_input(still)
            chain = _still_chain(still_i, seg, seg_len, i, tail)
        else:  # an unrecognised kind still gets a designed backdrop
            visual = None
            variant = seg.payload.get("variant", 0)
            still_i = _still_input(_backdrop_path(variant, seg.start))
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
        if seg_animation:
            meta["animation"] = seg_animation
        meta["filter"] = chain
        seg_meta.append(meta)
        # The frame plan is part of the segment's IDENTITY, not just its
        # inputs. The cache is keyed on the spec, and a beat whose asset
        # started moving can otherwise match a cached still: same size, same
        # filter shape, same declared inputs. Then the cut silently keeps
        # serving the frozen version.
        identity: tuple[str, ...] = ()
        if seg_animation:
            identity = (f"anim:{seg_animation['asset']}:"
                        f"{seg_animation['frames']}x{seg_animation['distinct']}",)
        seg_specs.append(SegmentSpec(
            index=i, kind=seg.kind, duration=seg_len,
            width=W, height=H, fps=fps,
            inputs=tuple(tuple(g) for g in seg_inputs),
            filter_chain=chain,
            layout=str(seg.payload.get("layout", "")),
            extra_identity=identity,
        ))

    # ------------------------------------------------- assemble the base
    # SEGMENTED (default): each beat encodes on its own, keyed by a content
    # hash, in parallel, resumably — then the clips are concatenated with
    # -c copy. SINGLE-GRAPH is the original monolithic filter_complex, kept
    # for correctness comparison.
    #
    # Either way the result is one base video that the global overlays — the
    # corner bug, disclaimer, captions, chapter stingers, doodles — composite
    # over. Those span segment boundaries, so they cannot be baked in per
    # segment.
    profile = encode_profile(settings, "long", draft=draft, preview=preview)
    seg_run: SegmentRun | None = None
    base_video: Path | None = None
    if settings.render_segmented:
        seg_run = encode_segments(
            seg_specs, settings.cache_dir / SEG_CACHE_DIRNAME, profile,
            total_threads=render_thread_budget(),
            fallback=lambda spec: _segment_fallback(spec, _backdrop_path, W, H, fps),
            on_progress=progress,
            # Detection proves the GPU can open one encode session, not
            # `workers` of them at once. If it runs out partway through, the
            # run finishes on the CPU instead of dying.
            software_profile=profile.software_equivalent(settings),
        )
        base_video = concat_clips(seg_run.clips(), rdir / "base.mp4")
        inputs = ["-i", str(base_video)]
        lines = [f"[0:v]fps={fps},setsar=1[v0]"]
    else:
        offset = 0
        for spec in seg_specs:
            for group in spec.inputs:
                inputs.extend(group)
            lines.append(_globalise(spec.filter_chain, offset, spec.index))
            offset += len(spec.inputs)
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

    # chapter stingers — the design system's section dividers, landing on the
    # first real cut at or after each chapter's own time, brief with a fade
    # (the intro covers act one, so these run from act two).
    #
    # The title is the SCRIPT'S, from its `=== CHAPTERS ===` trailer. This
    # used to space six hardcoded titles evenly across the runtime and ignore
    # both the trailer's times and its words, so every video announced
    # sections it did not have.
    seg_starts = [s.start for s in segments]
    used_ch: set[float] = set()
    stinger_meta: list[dict] = []
    transition_meta: list[dict] = []
    for k, (target, title) in enumerate(chapters, start=1):
        t = next((s for s in seg_starts
                  if s >= max(target, intro_dur) and s not in used_ch), None)
        if t is None or t < 0.6 or t > duration - 1.2:
            log.warning("chapters: %r at %.0fs has no cut to land on — skipped",
                        title, target)
            continue
        used_ch.add(t)
        num = f"{k + 1:02d}"     # the intro card is chapter one
        cs_path = rdir / f"chapter_{k}.png"
        if not cs_path.exists():
            chapter_stinger(settings, num, title, width=W, height=H).save(cs_path)
        layers.append(OverlayLayer(
            path=cs_path, x=0, y=0, t_start=t, t_end=min(t + 0.9, duration),
            fade_in=0.2, name=f"chapter_{k}",
        ))
        stinger_meta.append({"n": num, "title": title,
                             "script_t": round(target, 2), "t": round(t, 2)})

        # An ink transition on the act cut, under the stinger. Picked from a
        # frame-sequence family so the commissioned strips drop in as data;
        # until they ship, `transition_asset` returns None and the stinger
        # carries the cut on its own, as it always has.
        strip = transition_asset(kit, script.content_sha(), k, frame=(W, H))
        if strip is None:
            continue
        span = max(playback_seconds(strip), 0.25)
        tclip, (cw, ch) = render_clip(
            strip, rdir / f"transition_{k}.mov", duration_s=span, fps=fps,
            settings=settings,
            transform=transition_transform(strip, W, H, settings))
        layers.append(OverlayLayer(
            path=tclip, x=0, y=0, t_start=max(t - span * 0.5, 0.0),
            t_end=min(t + span * 0.5, duration), is_video=True,
            name=f"transition_{k}_{strip.name[:16]}"))
        transition_meta.append({"asset": strip.key, "t": round(t, 2)})

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
    #
    # Phrase captions, the same ones the short uses. The karaoke fill left a
    # narrow chip with ONE word lit and the rest of the line washed out to
    # near-invisible — unreadable at a glance, and it coloured the lit word
    # the same red the kit reserves for a down-move. A 16:9 line also has far
    # more room than a 9:16 one, so it takes a longer page.
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_phrase_ass(
        tts.words, play_res=(W, H), font_size=px(52), margin_v=px(120),
        margin_h=px(180), max_words=8, max_chars=46, duration=duration,
    ), encoding="utf-8")

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
        normalise_audio=not (settings.mocking_tts or draft or preview),
    )
    out_path = workspace / ("long_draft.mp4" if draft else "long_final.mp4")
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
        "segmented": bool(settings.render_segmented),
        "segment_cache_hits": (seg_run.cached if seg_run else 0),
        "segment_failures": [
            {"index": r.index, "detail": r.detail}
            for r in (seg_run.failures if seg_run else [])
        ],
        "layers": [
            {"name": l.name, "t_start": l.t_start, "t_end": l.t_end,
             "x": l.x, "y": l.y}
            for l in layers
        ],
        "segment_warnings": seg_warnings,
        "chapter_warnings": chapter_warnings,
        # What the video actually announces, against what the script asked
        # for. Read this rather than trusting the suite: the stingers used to
        # be six hardcoded titles spaced evenly, and every test passed.
        "chapters": [{"t": round(t, 2), "title": ti} for t, ti in chapters],
        "stingers": stinger_meta,
        "transitions": transition_meta,
        # The motion that reached the cut. Zero here means the long is back to
        # holding every drawing on frame 1.
        "animated_segments": sum(1 for m in seg_meta if m.get("animation")),
        "longest_host_beat_s": round(
            max((m["end"] - m["start"] for m in seg_meta
                 if m["kind"] == "host"), default=0.0), 2),
        "attributions": attributions,
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2), encoding="utf-8")
    return out_path, manifest_path
