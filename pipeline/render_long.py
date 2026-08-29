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
  * proof mode reuses them at FULL res and real fps on a cheap encode, so
    the operator can judge composition and type size — the one question
    draft and preview scale away — without buying a voice

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

from PIL import Image

from config import Settings
from pipeline.audio_assets import (
    ROOM_TONE_GAIN_DB,
    ROOM_TONE_NAME,
    audio_banner,
)
from pipeline.broll import ContentManager
from pipeline.company_data import prepare_screenshot
from pipeline.host import build_host_clip, pick_shot, place_on_room
from pipeline.chart import draw_declared
from pipeline.media_frames import FrameRotation, composite as frame_media
from pipeline.models import (
    CueKind,
    LongScript,
    SFX_KEYS,
    TagType,
    TTSResult,
    parse_scribble_payload,
)
from pipeline.plate_frames import playback_seconds, render_clip
from pipeline.plates import load_plates
from pipeline.rasters import (
    build_phrase_ass,
    cover_fill_frame,
    frames_to_alpha_clip,
    mark_frames,
    role,
    simple_text,
    solve_mark,
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
    unrenderable_long_tags,
)

log = logging.getLogger(__name__)

def _chapter_plan(script, duration: float,
                  warn: Callable[[str], None]) -> list[tuple[float, str, str]]:
    """`(time, title, type)` per chapter, off the script's own trailer.

    THERE IS NO FALLBACK LIST. The previous version carried six generic section
    titles and spaced them evenly across the runtime whenever the trailer was
    missing or unparseable, which put a caption on screen that was simply wrong
    — "the industry" over the valuation chapter. A chapter with no title is not
    drawn at all, and the operator is told which one and why.
    """
    out: list[tuple[float, str, str]] = []
    n = len(script.chapter_list)
    for i, ch in enumerate(script.chapter_list):
        # A trailer may omit timestamps; spread those across the runtime rather
        # than dropping them, because the ORDER is still information.
        t = ch.start_s if ch.start_s or i == 0 else duration * i / max(n, 1)
        out.append((t, ch.title, ch.type))
    if not out:
        warn("the script has no usable `=== CHAPTERS ===` trailer — no chapter "
             "openers will be drawn. The titles are the only place a section "
             "name appears on screen, so the cut will have none.")
    return out


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
    proof: bool = False,
    broll_overrides: dict[str, int] | None = None,
    as_of: str = "",
    company_data=None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[Path, Path]:
    """Render the LONG (or its low-res draft / full-res proof).

    Returns (mp4, manifest).
    """
    # Draft audio (the free local voice) has word timings that are exact per
    # sentence and interpolated within one. Good enough to judge pacing, not
    # good enough to be the master clock of something published — and the
    # whole pipeline trusts that clock. Enforced here rather than left to
    # discipline, because the failure is invisible: it renders fine, it is
    # just subtly out of sync.
    if not (draft or proof) and getattr(tts, "draft", False):
        raise RenderError(
            f"refusing to make a FINAL render from {tts.tier} draft audio — "
            f"its word timings are interpolated inside each sentence. Approve "
            f"the script so the paid voice runs, then render.")
    content = content or ContentManager(settings)
    duration = tts.duration_s
    # Tags that will not become cues. validate_long_script blocks on these
    # before approval, so reaching here means a path that skipped validation
    # (a draft, a CLI render) — say it anyway. A tag the writer asked for and
    # the renderer dropped is never a silent pass.
    for e, reason in unrenderable_long_tags(script):
        log.warning("tag: [%s] at char %d draws nothing — %s",
                    e.type.value, e.char_offset, reason or "unmapped tag type")
    cues = build_long_timeline(script, tts.words, duration)
    scribble_cues = [c for c in cues if c.kind is CueKind.SCRIBBLE]
    chapter_warnings: list[str] = []
    chapters = _chapter_plan(script, duration, chapter_warnings.append)
    for w in chapter_warnings:
        log.warning("chapters: %s", w)
    segments, seg_warnings = plan_long_segments(
        cues, duration,
        chapter_starts=[(t, ti) for t, ti, _ in chapters],
        min_readable_s=settings.long_min_readable_s,
        chapter_host_s=settings.long_chapter_host_s,
    )
    for w in seg_warnings:
        log.warning("segment plan: %s", w)

    # Four passes, each answering its own question (see config.py):
    # PREVIEW judges the edit at 480p/15fps, where the filter graph — not the
    # encode — is the cost. DRAFT is the half-res timing copy. PROOF keeps the
    # FULL frame, because whether type is legible at phone size is a
    # resolution question and both cheaper passes throw that evidence away;
    # it pays for the pixels out of the encoder instead. None re-calls TTS.
    FW, FH = settings.long_resolution          # full spec
    scale = (settings.preview_scale if preview
             else settings.draft_scale if draft
             else settings.proof_scale if proof else 1.0)
    W = int(FW * scale) // 2 * 2
    H = int(FH * scale) // 2 * 2
    fps = settings.preview_fps if preview else settings.fps

    rdir = workspace / ("render_long_preview" if preview
                        else "render_long_draft" if draft
                        else "render_long_proof" if proof else "render_long")
    rdir.mkdir(parents=True, exist_ok=True)

    website = str(company_data.get("website") or "") if company_data is not None else ""
    overrides = broll_overrides or {}
    reg = load_plates(settings.assets_dir)
    aspect = "16x9"

    px = lambda v: int(round(v * W / 1920))  # noqa: E731  (1920-wide design)

    def progress(done: int, total: int) -> None:
        log.info("segments %d/%d", done, total)
        if on_progress is not None:
            on_progress(done, total)

    # ------------------------------------------------ per-segment inputs
    inputs: list[str] = []
    lines: list[str] = []
    seg_meta: list[dict] = []

    # THE ROOM IS THE BOTTOM LAYER OF EVERY SHOT. It replaces the designed
    # filler backdrop, which existed because the old kit shipped no set: a beat
    # with no media got a generated card with the chapter's name printed on it.
    # There is a real room now, in nine angles, and a beat with nothing else in
    # it is simply the room.
    room_cache: dict[tuple[str, str], Path] = {}

    # Chapters are a TYPE and a TITLE. The title is the only thing that reaches
    # the screen, and it comes from what the director wrote — not from a
    # hardcoded list, which is how every video carried the same six section
    # names regardless of what its sections actually were.
    chapter_labels = [ch.title for ch in script.chapter_list]

    def _room_plate(role_name: str = "talk", seed: str = ""):
        return reg.room_for(role_name, aspect, seed=seed or script.ticker)

    def _room_still(variant: int, role_name: str = "talk") -> Path:
        """The room, as a still. The bottom layer when nothing else is on."""
        plate = _room_plate(role_name, seed=f"{script.ticker}|{variant % 3}")
        if plate is None:
            dest = rdir / "room_missing.png"
            if not dest.exists():
                Image.new("RGB", (W, H), role(settings, "ground")).save(dest)
            return dest
        key = (plate.key, "")
        if key not in room_cache:
            dest = rdir / f"room_{plate.name}.png"
            if not dest.exists():
                Image.open(plate.path).convert("RGB").resize(
                    (W, H), Image.LANCZOS).save(dest)
            room_cache[key] = dest
        return room_cache[key]

    def _chapter_opener(title: str, seg_i: int) -> Path:
        """A chapter opener is THE ROOM WITH THE TITLE IN ITS SLOT.

        Not a separate stinger family. The old path drew a full-frame card from
        a hardcoded list of six section names and a baked ordinal, so a chapter
        could not be moved, repeated or cut without the card lying about it.
        """
        from pipeline.plate_frames import render_still

        plate = _room_plate("establish", seed=f"{script.ticker}|{title}")
        if plate is None or "title" not in plate.slots:
            return _room_still(seg_i, "establish")
        dest = rdir / f"chapter_{seg_i}.png"
        img = render_still(plate, {"title": title}, settings, reg)
        img.convert("RGB").resize((W, H), Image.LANCZOS).save(dest)
        return dest

    # Back-compat shim for the few call sites that still ask for a backdrop by
    # variant and time.
    def _backdrop_path(variant: int, at: float | None = None) -> Path:
        return _room_still(variant)

    # ------------------------------------------------- plates, rendered
    # The director named the plate and wrote what goes on it. This puts that
    # text in the declared slots and does nothing else — it does not choose the
    # plate, and it does not work out a figure. Both of those used to happen
    # here, which is how a video ended up with visuals nobody had decided on.
    def _plate_art(seg, seg_i: int, value: str):
        """(path, is_video, (w, h), frame plan, key) for one [PLATE] beat."""
        from pipeline.plate_frames import (
            frame_indices, render_frame, render_still, unfilled_slots,
        )

        plate = reg.get(value)
        if plate is None:
            log.warning("plate %s is not in the registry — the beat draws the "
                        "room instead", value)
            return _room_still(seg_i), False, None, (), None

        values = dict(seg.payload.get("values") or {})
        # An empty cell means NO DATA in this library, so this reports rather
        # than substitutes. Inventing a figure is the one thing forbidden here.
        empty = unfilled_slots(plate, values)
        if empty:
            log.info("plate %s leaves %s empty", value, ", ".join(empty))

        if not plate.animated:
            dest = rdir / f"plate_{seg_i}_{plate.name[:24]}.png"
            img = render_still(plate, values, settings, reg).convert("RGBA")
            # A plate that reserves a data region gets its path drawn through
            # the figures the DIRECTOR wrote into it. Without this a charts/ or
            # cycles/ plate is a set of labels around an empty box.
            if draw_declared(reg, plate, values, img, seed=f"{plate.key}|{seg_i}"):
                log.debug("%s: drew its declared series", plate.key)
            if img.size != (W, H):
                img = img.resize((W, H), Image.LANCZOS)
            img.save(dest)
            return dest, False, img.size, (), plate.key

        # A two-frame boil, encoded ONCE at its own rate. Walking the beat's
        # whole frame plan and encoding every output frame turned a two-frame
        # loop into 240 frames of 4K RGBA — a 172 MB clip for eight seconds of
        # a drawing that has two states. The plate is also brought down to the
        # OUTPUT size here rather than in the encoder, which is where the bytes
        # actually went.
        span = max(seg.end - seg.start, playback_seconds(plate))
        plan = frame_indices(plate, span, fps)
        frames = []
        for idx in range(plate.frame_count):
            img = render_frame(plate, idx, values, settings, reg)
            frames.append(img.resize((W, H), Image.LANCZOS))
        dest = rdir / f"plate_{seg_i}_{plate.name[:24]}.mov"
        frames_to_alpha_clip(frames, max(plate.fps or 2, 1), dest)
        return dest, True, (W, H), tuple(plan), plate.key

    def _plate_still(seg, seg_i: int, value: str) -> Path:
        return _plate_art(seg, seg_i, value)[0]

    # ------------------------------------------------ foreign media, framed
    # [CLIP], [IMG], [SHOW ARTICLE] and [SHOW FILING] land INSIDE a frames/
    # plate. Raw and full-frame they destroy the drawn surface the rest of the
    # video is built on, and the treatments rotate so consecutive ones differ.
    frame_rotation = FrameRotation()

    def _frame_plate(kind, *, needs_media: bool = True):
        """The next frames/ plate in the rotation, or None when unavailable.

        `needs_media` is True everywhere here: this path always has a real
        image or clip in hand, so it needs a plate with an aperture. The
        capture frame is for a document transcribed into slots and has none.
        """
        from pipeline.media_frames import frame_for

        return frame_for(reg, frame_rotation, aspect, kind=kind,
                         needs_media=needs_media)

    def _frame_bg(frame, seg, seg_i: int) -> tuple[Path, tuple[int, int, int, int]]:
        """The empty frame as a background, and the aperture to play inside.

        For FOOTAGE, which cannot be composited frame by frame in Pillow: the
        plate is rendered once with its caption and source, and ffmpeg overlays
        the clip into the aperture.
        """
        from pipeline.media_frames import aperture
        from pipeline.plate_frames import render_still

        dest = rdir / f"frame_{seg_i}.png"
        values = {k: v for k, v in (seg.payload.get("values") or {}).items()
                  if k in frame.slots}
        img = render_still(frame, values, settings, reg)
        img.convert("RGB").resize((W, H), Image.LANCZOS).save(dest)
        ap = aperture(frame) or (0, 0, W, H)
        k = W / frame.delivered[0]
        return dest, (int(ap[0] * k), int(ap[1] * k),
                      max(int(ap[2] * k), 1), max(int(ap[3] * k), 1))

    def _framed_media(seg, seg_i: int, media_path: Path, kind) -> Path:
        frame = _frame_plate(kind)
        if frame is None:
            return media_path
        try:
            media = Image.open(media_path).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 — never fatal
            log.warning("could not open %s (%s) — unframed", media_path, exc)
            return media_path
        values = {k: v for k, v in (seg.payload.get("values") or {}).items()
                  if k in frame.slots}
        out = frame_media(reg, frame, media, settings, values=values)
        dest = rdir / f"framed_{seg_i}.png"
        out.convert("RGB").resize((W, H), Image.LANCZOS).save(dest)
        return dest

    def _still_chain(input_i: int, seg, seg_len: float, seg_i: int,
                     tail: str) -> str:
        """Every still is held. There is no drift on anything."""
        return _hold_still_chain(input_i, seg_len, W, H, tail)

    # ------------------------------------------------------- the host rig
    # Dennis is composited per segment onto the ROOM, lip-synced to that
    # segment's slice of the voice-over. The pose steps through a role's bank
    # with the beat index so a long cut never returns to an identical frame.
    #
    # He is a 9:16 alpha CUT-OUT and the room is the set he stands in — which
    # is what removed the whole sizing problem the old rig had. The v1 host
    # shots were composed 16:9 cards, so sizing one the way a cut-out is sized
    # made it 82% of the frame WIDTH and, in a two-shot, covered the panel he
    # was meant to be standing beside. There is nothing to guess now: the room
    # declares a host-anchor whose HEIGHT is his target height, and his floor
    # line sits on its bottom edge.

    # How often each pose has been used, so a pose the kit caps (head-in-hands
    # is limit 1) is not reached for twice.
    host_used: dict[str, int] = {}

    # What the face did, per segment. Over forty minutes the host is the
    # most-viewed element in the channel and the easiest to leave static
    # without noticing, so the manifest records it.
    host_motion: list[dict] = []

    def _host_input(seg_i: int, seg, seg_len: float, *, panel: bool = False):
        """Add the host clip as an input. Returns (index, x, y) or None.

        The room this beat is shot in decides his size and where he stands.
        """
        role_name = "panel" if panel else "beat"
        room = _room_plate(role_name if panel else "talk",
                           seed=f"{script.ticker}|{seg_i % 3}")
        # He is composited per output frame, so he is loaded at the size he
        # will be SHOWN at rather than at his delivered 2160x3840. Without
        # this every frame of every host beat is a 4K RGBA resize.
        shot_probe = pick_shot(reg, role_name, seg_i, used=host_used)
        target_h = H
        if room is not None and shot_probe is not None:
            placed_probe = place_on_room(room, shot_probe)
            if placed_probe is not None:
                target_h = max(int(placed_probe.height * (W / room.delivered[0])), 1)
        motion: dict = {}
        built = build_host_clip(
            tts.words, seg.start, seg.end, rdir / f"host_{seg_i}.mov",
            reg=reg, settings=settings, fps=fps, display_h=target_h,
            role=role_name, shot_index=seg_i, used=host_used, report=motion,
        )
        if built is None:
            return None
        if motion:
            host_motion.append({"segment": seg_i, **motion})
            host_used[motion.get("pose", "")] = (
                host_used.get(motion.get("pose", ""), 0) + 1)

        clip_path, (hw, hh) = built
        shot = pick_shot(reg, role_name, seg_i, used=host_used)
        placed = place_on_room(room, shot) if (room and shot) else None
        if placed is not None:
            k = W / room.delivered[0]
            return (_add_input(["-i", str(clip_path)]),
                    int(placed.x * k), int(placed.y * k),
                    max(int(placed.width * k), 1), max(int(placed.height * k), 1))
        return (_add_input(["-i", str(clip_path)]),
                int((W - hw) / 2), max(H - hh, 0), hw, hh)

    def _overlay_chain(bg_i: int, fg_i: int, x: int, y: int,
                       seg_len: float, seg_i: int, tail: str) -> str:
        """Room + alpha host clip -> one concat-ready segment stream."""
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
                              w: int, h: int, seg_len: float, tail: str, *,
                              loop: bool = False) -> str:
        """As `_overlay_chain`, but the layer is scaled into its box first.

        `loop` is what a BOIL needs. A two-frame loop is encoded once at its
        own 2fps and then repeated for the beat; cloning its last frame instead
        — which is what `tpad` does — freezes the drawing after half a second,
        and a frozen plate beside a boiling room is the exact thing the boil
        exists to prevent.
        """
        fg = (f"[{fg_i}:v]loop=loop=-1:size=32767:start=0,setpts=N/FRAME_RATE/TB,"
              f"trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,scale={w}:{h}[hfg];"
              if loop else
              f"[{fg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
              f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
              f"trim=0:{seg_len:.4f},scale={w}:{h}[hfg];")
        return (
            f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}[hbg];"
            + fg +
            f"[hbg][hfg]overlay={x}:{y}:eof_action=repeat"
            f"{tail}"
        )

    # ----------------------------------------------- the two-shot, on the room
    # A two-shot is the ROOM, the evidence, and Dennis standing beside it. It
    # used to be three finished designs stacked in one frame: a filler backdrop
    # with its own giant ticker and grid, the evidence card on top of that, and
    # a whole 16:9 host SLIDE over both, carrying its own headline and often its
    # own illustration. Every edge showed and two unrelated headlines argued
    # with each other and with the caption.
    #
    # One set. One piece of evidence. One cut-out standing in it.

    def _host_column(room, shot) -> tuple[int, int, int]:
        """(x, width, height) of the host on this room, in frame pixels."""
        placed = place_on_room(room, shot) if (room and shot) else None
        if placed is None:
            return W - px(520), px(460), int(H * 0.7)
        k = W / room.delivered[0]
        return (int(placed.x * k), max(int(placed.width * k), 1),
                max(int(placed.height * k), 1))

    def _evidence_box(room, shot, two_shot: bool) -> tuple[int, int, int, int]:
        """(x, y, max width, max height) for the evidence, beside the host."""
        if not two_shot:
            ew, eh = int(W * 0.86), int(H * 0.86)
            return int((W - ew) / 2), int((H - eh) / 2), ew, eh
        hx, hw, _ = _host_column(room, shot)
        # Whichever side of him has more room. He is placed by the ROOM, so
        # which side that is depends on the angle rather than on a flag.
        left_w, right_w = hx - px(120), W - (hx + hw) - px(120)
        if right_w >= left_w:
            return hx + hw + px(60), int(H * 0.10), max(right_w, px(400)), int(H * 0.80)
        return px(60), int(H * 0.10), max(left_w, px(400)), int(H * 0.80)

    def _fit_evidence(w: int, h: int, seg_i: int, *,
                      two_shot: bool) -> tuple[int, int]:
        """The size an evidence image of (w, h) takes in its column."""
        room = _room_plate("panel" if two_shot else "talk",
                           seed=f"{script.ticker}|{seg_i % 3}")
        shot = pick_shot(reg, "panel", seg_i, used=host_used) if two_shot else None
        _, _, max_w, max_h = _evidence_box(room, shot, two_shot)
        ratio = min(max_w / max(w, 1), max_h / max(h, 1))
        return max(int(w * ratio), 1), max(int(h * ratio), 1)

    def _panel_plate(size: tuple[int, int], seg_i: int, dest: Path, *,
                     two_shot: bool) -> tuple[Path, int, int]:
        """The room (and the figure) with a HOLE the evidence goes in.

        Returns (background, x, y) — the origin an evidence image or clip of
        `size` should be composited at, so an animated beat overlays its alpha
        strip on exactly the composition a still gets pasted into.
        """
        room = _room_plate("panel" if two_shot else "talk",
                           seed=f"{script.ticker}|{seg_i % 3}")
        shot = pick_shot(reg, "panel", seg_i, used=host_used) if two_shot else None
        base = (Image.open(room.path).convert("RGB").resize((W, H), Image.LANCZOS)
                if room is not None
                else Image.new("RGB", (W, H), role(settings, "ground")))
        bx, by, max_w, max_h = _evidence_box(room, shot, two_shot)
        ew, eh = size
        ex = bx + max(int((max_w - ew) / 2), 0)
        ey = by + max(int((max_h - eh) / 2), 0)
        if shot is not None and room is not None:
            placed = place_on_room(room, shot)
            if placed is not None:
                k = W / room.delivered[0]
                fig = Image.open(shot.pose.path).convert("RGBA").resize(
                    (max(int(placed.width * k), 1), max(int(placed.height * k), 1)),
                    Image.LANCZOS)
                base.paste(fig, (int(placed.x * k), int(placed.y * k)), fig)
        base.save(dest)
        return dest, ex, ey

    def _panel_frame(still: Path, seg_i: int, dest: Path, *,
                     two_shot: bool = True) -> Path:
        """The two-shot, as ONE composition: the room, the evidence, Dennis."""
        panel = Image.open(still).convert("RGBA")
        ew, eh = _fit_evidence(panel.width, panel.height, seg_i,
                               two_shot=two_shot)
        panel = panel.resize((ew, eh), Image.LANCZOS)
        bg, ex, ey = _panel_plate((ew, eh), seg_i, dest, two_shot=two_shot)
        base = Image.open(bg).convert("RGB")
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
            bg_i = _still_input(_room_still(variant))
            host = _host_input(i, seg, seg_len)
            if host is None:
                chain = _still_chain(bg_i, seg, seg_len, i, tail)
            else:
                host_i, hx, hy, hw, hh = host
                chain = _scaled_overlay_chain(bg_i, host_i, hx, hy, hw, hh,
                                              seg_len, tail)
        elif seg.kind == "clip":
            # Footage plays inside a frames/ plate rather than edge to edge.
            # Raw and full-frame it destroys the drawn surface the rest of the
            # video is built on: thirty minutes of ink, then a 4K stock shot,
            # then back — two videos cut together.
            visual = content.resolve_clip(value, overrides.get(value, 0))
            frame_plate = _frame_plate(CueKind.CLIP)
            clip_i = _add_input(["-i", str(visual.path)])
            if frame_plate is None:
                chain = _clip_motion(clip_i)
            else:
                bg, (ax, ay, aw, ah) = _frame_bg(frame_plate, seg, i)
                bg_i = _still_input(bg)
                chain = _scaled_overlay_chain(bg_i, clip_i, ax, ay, aw, ah,
                                              seg_len, tail)
        elif seg.kind == "filing":
            if value not in shot_cache:
                shot_cache[value] = prepare_screenshot(
                    workspace / value, rdir / f"shot_{Path(value).stem}.png", settings
                )
            visual = None
            still_i = _still_input(
                _framed_media(seg, i, shot_cache[value], CueKind.FILING))
            chain = _still_chain(still_i, seg, seg_len, i, tail)
        elif seg.kind == "screengrab":
            # operator-supplied capture — image or short clip, framed either way
            visual = content.resolve_screengrab(value)
            if visual.is_video:
                clip_i = _add_input(["-i", str(visual.path)])
                frame_plate = _frame_plate(CueKind.SCREENGRAB)
                if frame_plate is None:
                    chain = _clip_motion(clip_i)
                else:
                    bg, (ax, ay, aw, ah) = _frame_bg(frame_plate, seg, i)
                    bg_i = _still_input(bg)
                    chain = _scaled_overlay_chain(bg_i, clip_i, ax, ay, aw, ah,
                                                  seg_len, tail)
            else:
                still_i = _still_input(
                    _framed_media(seg, i, visual.path, CueKind.SCREENGRAB))
                chain = _still_chain(still_i, seg, seg_len, i, tail)
        elif seg.kind in ("plate", "chapter"):
            # The plate the DIRECTOR named, with the text they wrote in it.
            visual = None
            art, is_video, size, plan, key = _plate_art(seg, i, value)
            two_shot = seg.payload.get("layout") == "two-shot"
            if is_video:
                # A boiling plate is an alpha clip, so the background it plays
                # on is the same composition a still gets pasted into.
                ew, eh = _fit_evidence(size[0], size[1], i, two_shot=two_shot)
                bg, ex, ey = _panel_plate((ew, eh), i, rdir / f"bg_{i}.png",
                                          two_shot=two_shot)
                bg_i = _still_input(bg)
                fg_i = _add_input(["-i", str(art)])
                chain = _scaled_overlay_chain(bg_i, fg_i, ex, ey, ew, eh,
                                              seg_len, tail, loop=True)
                seg_animation = {"asset": key, "frames": len(plan),
                                 "distinct": len(set(plan))}
            else:
                still = _panel_frame(art, i, rdir / f"panel_{i}.png",
                                     two_shot=two_shot)
                still_i = _still_input(still)
                chain = _still_chain(still_i, seg, seg_len, i, tail)
        elif seg.kind in ("img", "chart", "meme"):
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
            else:  # meme — compose the freeze-frame full-frame so it never
                   # sits letterboxed on black; it is then held still
                visual = content.resolve_meme(value)
                if visual.key not in meme_frame_cache:
                    dest = rdir / f"meme_frame_{len(meme_frame_cache)}.png"
                    cover_fill_frame(visual.path, W, H, keep_min=1.1,
                                     ground=role(settings, "ground"),
                                     line=role(settings, "structure")).save(dest)
                    meme_frame_cache[visual.key] = dest
                still = meme_frame_cache[visual.key]
            # A chart is a PLATE with a path drawn in it, so it plays as a
            # two-shot: Dennis stays in frame beside it and the cut never
            # leaves the host. Photographs and memes are foreign media and go
            # inside a frames/ plate instead.
            if seg.kind in ("img", "meme"):
                still = _framed_media(
                    seg, i, still,
                    CueKind.IMG if seg.kind == "img" else CueKind.MEME)
            elif seg.payload.get("layout") == "two-shot":
                still = _panel_frame(still, i, rdir / f"panel_{i}.png")
            still_i = _still_input(still)
            chain = _still_chain(still_i, seg, seg_len, i, tail)
        else:  # an unrecognised kind still gets the room
            visual = None
            variant = seg.payload.get("variant", 0)
            still_i = _still_input(_room_still(variant))
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
    profile = encode_profile(settings, "long", draft=draft, preview=preview,
                             proof=proof)
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

    # The opening title, on the kit's loudest headline band — the one the kit's
    # own notes reserve for once per video. It used to be a composed card drawn
    # by rasters.py over a brand scene, which is a second visual language for
    # the one frame everybody sees first.
    from pipeline.plate_frames import render_still as _render_still

    intro_dur = min(2.6, duration * 0.5)
    intro_path = rdir / "intro_card.png"
    intro_plate = reg.get(reg.aspect_key("paper/headline-band-t3", aspect) or "")
    if intro_plate is not None:
        _render_still(intro_plate, {
            "kicker": script.ticker.upper(),
            "headline": (script.chapter_list[0].title if script.chapter_list
                         else settings.brand_tagline.lower()),
            "sub": settings.brand_tagline.lower(),
        }, settings, reg).convert("RGB").resize((W, H), Image.LANCZOS).save(intro_path)
    else:
        Image.new("RGB", (W, H), role(settings, "ground")).save(intro_path)
    layers.append(OverlayLayer(
        path=intro_path, x=0, y=0, t_start=0.0, t_end=intro_dur, name="intro_card",
    ))

    # Chapter openers — the room with the title in its slot, landing on the
    # first real cut at or after each chapter's own time.
    #
    # The title is the SCRIPT'S, from its `=== CHAPTERS ===` trailer. This used
    # to space six hardcoded titles evenly across the runtime and ignore both
    # the trailer's times and its words, so every video announced sections it
    # did not have.
    seg_starts = [s.start for s in segments]
    used_ch: set[float] = set()
    stinger_meta: list[dict] = []
    transition_meta: list[dict] = []
    for k, (target, title, ctype) in enumerate(chapters, start=1):
        t = next((s for s in seg_starts
                  if s >= max(target, intro_dur) and s not in used_ch), None)
        if t is None or t < 0.6 or t > duration - 1.2:
            log.warning("chapters: %r at %.0fs has no cut to land on — skipped",
                        title, target)
            continue
        used_ch.add(t)

        # A CHAPTER OPENER IS THE ROOM WITH THE TITLE IN ITS SLOT.
        #
        # There is no stinger family any more, and no ordinal. The old card
        # printed "01"…"14" into the artwork, which is why a chapter could not
        # be moved, repeated or cut without the card lying about it — and a
        # TYPE may legitimately appear twice in one video under two titles.
        cs_path = _chapter_opener(title, k)
        layers.append(OverlayLayer(
            path=cs_path, x=0, y=0, t_start=t, t_end=min(t + 1.6, duration),
            fade_in=0.2, name=f"chapter_{k}",
        ))
        stinger_meta.append({"type": ctype, "title": title,
                             "script_t": round(target, 2), "t": round(t, 2)})

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

    # Annotations (TOP layer, riding over whatever segment shows).
    #
    # An annotation is drawn in ATTENTION and therefore SPENDS the frame's one
    # attention, which is why there is one family and no separate doodle layer.
    # [DOODLE] used to put a second procedural drawing in a corner on top of
    # whatever was already there — a second visual language, competing with the
    # thing it was meant to punctuate.
    for k, c in enumerate(scribble_cues):
        parsed = parse_scribble_payload(c.payload["value"])
        if parsed is None:
            continue
        style, target = parsed
        hold = float(c.payload.get("hold", 2.0))
        sw, sh = px(700), px(460)
        # The mark draws itself on, in attention, over the current frame. It is
        # placed centrally here because the LONG has no word-level geometry to
        # solve against — solve_mark does that where a slot box is known.
        frames = mark_frames(settings, sw, sh, style=style.value, fps=fps,
                             draw_seconds=min(hold, 0.5),
                             seed=f"{script.ticker}|scr|{k}")
        if not frames:
            continue
        hold_frames = max(int(hold * fps) - len(frames), 0)
        frames = frames + [frames[-1]] * hold_frames
        clip = frames_to_alpha_clip(frames, fps, rdir / f"scribble_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=int((W - sw) / 2), y=int((H - sh) / 2),
            t_start=c.t, t_end=min(c.t + hold + 0.5, duration),
            is_video=True, hold=True, name=f"scribble_{k}",
        ))

    # corner bug: ticker + as-of date (top-right; the as-of stays visible)
    bug_text = script.ticker + (f" · as of {as_of}" if as_of else "")
    bug = simple_text(settings, bug_text, font_size=px(34),
                      fill=(*role(settings, "structure"), 220), stroke_width=0)
    bug_path = rdir / "corner_bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=W - bug.width - px(36), y=px(30),
        t_start=0.0, t_end=duration, name="corner_bug",
    ))

    # Branded strip: ticker + channel tagline. Persistent, TOP-left — moved
    # off the bottom so it can never clip or stack with the caption band.
    # Plain type on the ground, not a drawn card: the frame under it is already
    # a drawn room, and a second card on top of it is a second surface.
    lt = simple_text(settings, f"${script.ticker} · {settings.brand_tagline.lower()}",
                     font_size=px(34), fill=(*role(settings, "structure"), 220),
                     stroke_width=0)
    lt_path = rdir / "lower_third.png"
    lt.save(lt_path)
    layers.append(OverlayLayer(
        path=lt_path, x=px(36), y=px(30),
        t_start=0.0, t_end=duration, name="lower_third",
    ))

    disc = simple_text(settings, settings.disclaimer_text, font_size=px(26),
                       fill=(*role(settings, "neutral-data"), 235),
                       stroke_width=0)
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
        tts.words, settings=settings, play_res=(W, H), font_size=px(52), margin_v=px(120),
        margin_h=px(180), max_words=8, max_chars=46, duration=duration,
    ), encoding="utf-8")

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, gain_db=0.0, voice=True)]
    music = settings.assets_dir / "music" / "dennis_bed.m4a"
    if music.exists():
        audio.append(AudioTrack(path=music, gain_db=settings.music_gain_db, loop=True))
    # The room, under everything. A forty-minute cut with digital silence
    # between words is the clearest tell that it was assembled.
    room = settings.assets_dir / "sfx" / ROOM_TONE_NAME
    if room.exists():
        audio.append(AudioTrack(path=room, gain_db=ROOM_TONE_GAIN_DB, loop=True))
    banner = audio_banner(settings)
    if banner:
        log.warning("%s", banner)
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
        normalise_audio=not (settings.mocking_tts or draft or preview
                             or getattr(tts, "draft", False)),
    )
    out_path = workspace / ("long_draft.mp4" if draft
                            else "long_proof.mp4" if proof
                            else "long_final.mp4")
    composite_video(spec, profile, settings.audio_bitrate, out_path)

    rendered = ffprobe_duration(out_path)
    if abs(rendered - duration) > 0.7:
        raise RenderError(
            f"rendered duration {rendered:.2f}s deviates from the audio master "
            f"clock {duration:.2f}s"
        )

    manifest_path = workspace / ("render_long_draft_manifest.json" if draft
                                 else "render_long_proof_manifest.json" if proof
                                 else "render_long_manifest.json")
    attributions = sorted({m["attribution"] for m in seg_meta
                           if m.get("attribution")})
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "draft": draft,
        "proof": proof,
        # The audio tier, carried on the manifest so "is this shippable?" is
        # answerable from the artefact rather than from whoever ran it. A
        # proof is real pictures over a free voice: everything below is what
        # a final would have used, the voice is not.
        "audio_tier": getattr(tts, "tier", ""),
        "draft_audio": bool(getattr(tts, "draft", False)),
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
        "chapters": [{"t": round(t, 2), "title": ti, "type": ct}
                     for t, ti, ct in chapters],
        "stingers": stinger_meta,
        "transitions": transition_meta,
        # The motion that reached the cut. Zero here means the long is back to
        # holding every drawing on frame 1.
        "animated_segments": sum(1 for m in seg_meta if m.get("animation")),
        "longest_host_beat_s": round(
            max((m["end"] - m["start"] for m in seg_meta
                 if m["kind"] == "host"), default=0.0), 2),
        # The face. `blinks: 0` with `shots_with_blink: 0` means the artwork
        # has not shipped `-blink` strips yet and every shot boiled, which is
        # the designed fallback. `blinks: 0` with shots that HAVE the strips
        # is the bug.
        "host_motion": host_motion,
        "blinks": sum(m.get("blinks", 0) for m in host_motion),
        "shots_with_blink": sum(1 for m in host_motion if m.get("has_blink")),
        "shots_with_idle": sum(1 for m in host_motion if m.get("has_idle")),
        "attributions": attributions,
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2), encoding="utf-8")
    return out_path, manifest_path
