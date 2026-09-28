"""LONG host-anchored engine — 16:9 deadpan deep-dive (§5).

Structure:
  * clean audio from the tag-stripped narration (cached TTS)
  * `build_long_timeline` resolves every tag to its spoken word
  * `plan_long_segments` tiles the full duration with host beats and the
    evidence he cuts away to
  * each beat encodes on its own (segmented, cached, in parallel) and the
    beats are concatenated; the overlays that span beats (opening title,
    chapter bumpers, corner bug, top strip, disclaimer, marks, captions) go
    over that base in one pass, with VO + room tone + SFX in a single amix
  * draft mode reuses the same cached audio and graph at low res /
    ultrafast (never re-calls TTS)
  * proof mode reuses them at FULL res and real fps on a cheap encode, so
    the operator can judge composition and type size — the one question
    draft and preview scale away — without buying a voice

NOTHING PANS OR ZOOMS. Motion is the kit's own: the rooms' loops, the host
rig's talk, idle and blink strips, the plates' boil, the kit's moves where a
beat declares one, and real footage. Every still is scale + pad on the kit's
ground, held.

DENNIS IS THE BASE FRAME (§editing): this is a talking-host show. Untagged
narration is the host on screen, a cut-out standing in one of the kit's rooms
and lip-synced to the voice-over by `pipeline.host`; a tag means leave his
face for a piece of evidence and hold it long enough to read. Nothing flashes
by: data visuals cannot be cut short by a later tag, that tag is deferred
instead. Marks ride ON TOP, including over the host.

Segment kinds:
  host        Dennis talking in a room — the default frame
  plate       the kit plate the writer named, with the words they wrote in its
              slots; a two-shot beside the host unless a mark needs the frame
  chapter     a chapter's plate, the same way
  clip        stock footage, played inside a kit frames/ plate
  screengrab  an operator-dropped capture, framed the same way
  filing      the filing screenshot, framed, with design's source tag
  img         real operations/product imagery, full-frame and held still
  chart       an auto-generated chart — a two-shot beside the host
  meme        a freeze-frame from the owned library, full-frame

A two-shot is composed as ONE still: the room, the evidence, and the host
standing beside it. Chapter boundaries reserve a host beat on each side, so a
chapter opens and closes on his face, and from the second chapter on a kit
bumper names it.

Kit artwork is addressed through the registry as an ASSET, not a path, so a
tag's `= value` reaches the drawing's declared boxes and a one-shot shows its
end state rather than freezing on frame 1. Captions are phrase by phrase in
the kit's faces. Every visual lands on its anchor word (or the first moment
after it that is free); there is no verdict stamp — the video ends on
whatever deadpan line the script wrote.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Callable

from PIL import Image

from config import Settings
from pipeline.audio_assets import audio_banner
from pipeline.broll import ContentManager
from pipeline.company_data import prepare_screenshot
from pipeline.host import (build_host_clip, cast_pose, frame_shot, front_of,
                           host_shot, pick_shot, place_on_room, stands_on)
from pipeline.chart import declared_layer, draw_declared
from pipeline.media_frames import FrameRotation, composite as frame_media
from pipeline.models import (
    CueKind,
    LongScript,
    SFX_KEYS,
    TTSResult,
    parse_scribble_payload,
)
from pipeline.bumper import bumper_clip, tick_start, wipe_clip
from pipeline.plate_frames import drawn_box, frame_indices, playback_seconds
from pipeline.plates import _prefer_unused, at_episode_hour, load_plates
from pipeline.sound import (DEFAULT_LEAD_S, EFFECT_KEYS, Cut, Move, Voicing,
                            cue_lead_s, manifest_rows, measure_lufs,
                            move_cues, placeholders_played, room_track,
                            sound_summary, theme_tracks, wipe_cues)
from pipeline.rasters import (
    build_phrase_ass,
    cover_fill_frame,
    frames_to_alpha_clip,
    mark_frames,
    role,
    simple_text,
    solve_mark,
    SCRIBBLE_MARKS,
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
)
from pipeline.segments import (
    CACHE_DIRNAME as SEG_CACHE_DIRNAME,
    SegmentRun,
    SegmentSpec,
    concat_clips,
    encode_segments,
    prune_cache,
)
from pipeline.timeline import (
    MIN_SEGMENT_S,
    build_long_timeline,
    plan_long_segments,
    plan_writer_moves,
    plan_writer_sources,
    scene_in_force,
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


def _chapter_cuts(chapters: list[tuple[float, str, str]], seg_starts: list[float],
                  *, intro_dur: float, duration: float) -> list[float | None]:
    """The cut each chapter's opener lands on, or None where it has none:
    the first cut at or after the chapter's own time, each cut used once."""
    used: set[float] = set()
    out: list[float | None] = []
    for target, _title, _type in chapters:
        t = next((s for s in seg_starts
                  if s >= max(target, intro_dur) and s not in used), None)
        if t is None or t < 0.6 or t > duration - 1.2:
            out.append(None)
            continue
        used.add(t)
        out.append(t)
    return out


def _cleared(t: float, covers: list[tuple[float, float]]) -> float:
    """The first moment at or after `t` that no full-frame cover is on.

    A move played under the opening title, a chapter bumper or a wipe's cover
    is a move nobody sees, so a beat that opens under one starts its moves
    when it lifts.
    """
    for a, b in sorted(covers):
        if a <= t + 1e-6 < b:
            t = b
    return t


# How long the opening title holds over the first frames. It is opaque, so
# whatever the first host beat is shot in is not seen until it lifts.
INTRO_CARD_S = 2.6

# THE LOWER THIRD'S SIZE AND PLACE, in the 1920-wide design's pixels. Design
# drew it 820 wide, and at that size its right edge runs into the close-up's
# head (from x 780). At 640 it clears the head, its foot (y 182) clears every
# standing figure (panel-left, the highest, stands him from y 228), and the
# channel's line is still legible; at 500 it was not.
LOWER_THIRD_W = 640
LOWER_THIRD_AT = (24, 20)
# A window of him shorter than this gets no lower third: on and off inside a
# second reads as a flicker, not a strip.
LOWER_THIRD_MIN_S = 1.5


def _on_him(segments, covers: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The stretches the frame is a beat of him with nothing covering it.

    Consecutive beats of him are one stretch, so the strip does not blink on
    the cut between two of his shots; a cover (the opening title, a chapter
    card, a wipe) is taken out of it.
    """
    runs: list[list[float]] = []
    for sg in segments:
        if sg.kind != "host":
            continue
        if runs and abs(runs[-1][1] - sg.start) < 1e-6:
            runs[-1][1] = sg.end
        else:
            runs.append([sg.start, sg.end])
    out: list[tuple[float, float]] = []
    for a, b in runs:
        pieces = [(a, b)]
        for ca, cb in sorted(covers):
            nxt = []
            for pa, pb in pieces:
                if cb <= pa or ca >= pb:
                    nxt.append((pa, pb))
                    continue
                if ca > pa:
                    nxt.append((pa, ca))
                if cb < pb:
                    nxt.append((cb, pb))
            pieces = nxt
        out.extend((pa, pb) for pa, pb in pieces if pb - pa >= LOWER_THIRD_MIN_S)
    return out

# THE COLD OPEN STARTS WIDE. A long opened on the same talking-head angle as
# the hundred host beats after it, so its first frame said nothing about
# where we are. The kit ships wide angles for exactly this (the `opener`
# role: desk-wide, and window-wide since rebuild-39), and window-wide was
# drawn as the establishing shot — so it is preferred, and desk-wide takes
# its turn when the last few videos all opened on the window. board-wide is
# held back by the curation and never reaches the role, so it is not here.
COLD_OPEN_PREFERRED = "room/window-wide"

# THE ROLES THE LONG CASTS FROM. The long has no shot file (the chapter
# template engine that had one is retired), so the kit audit cannot read its
# rooms and poses off a template the way it reads a short's: every room and
# every standing pose below is asked for by ROLE, and the kit answers with an
# angle. `gates.reachable_plates` reads these instead. A role asked for below
# and missing here is a drawing every long puts on screen that the audit
# reports as having no route to one.
LONG_ROOM_ROLES = ("talk", "panel")          # and the opener, `opener_role`
LONG_HOST_ROLES = ("beat", "panel", "rests-on")


def opener_role(reg) -> str:
    """The role the cold open and a chapter card's room are cast from.

    `opener` where the kit publishes one: the rooms with a `title` slot.
    `establish` also holds rooms with no slot, so it is only the fallback.
    """
    return "opener" if reg.room_roles.get("opener") else "establish"


def cold_open_room(reg, aspect: str, *, recent=(), kept: str = "") -> str:
    """The base key of the room the cold open's first shot is in, or "".

    `kept` is what an earlier pass of THIS video opened on, and wins while
    the kit still offers it: a proof that opens on the window and a final
    that opens on the desk are two different videos. `recent` is what the
    last few videos opened on, newest first; it is a preference to move off,
    never a constraint, exactly as `_prefer_unused` is for every other room.

    Only angles someone can stand in: the first shot is Dennis talking.
    """
    role_name = opener_role(reg)
    options = [k for k in reg.angles_for(role_name, aspect, reg.hour)
               if (p := reg.get(k)) is not None and not p.refuses_host]
    if not options:
        return ""
    base = {k: reg.base_key(k) for k in options}
    if kept and kept in base.values():
        return next(k for k in options if base[k] == kept)
    options.sort(key=lambda k: not base[k].startswith(COLD_OPEN_PREFERRED))
    return _prefer_unused(options, reg.base_keys(recent))[0]


def _recorded_cold_opens(settings, workspace: Path) -> tuple[list[str], str]:
    """`(recent, kept)`: the rooms recent videos opened on, and this one's.

    Off the manifests' own `cold_open_room`, and NOT off `plates_used`: every
    long draws both wide rooms somewhere as chapter openers, so "used
    recently" is true of both on every video and would never turn. Forgiving
    in the way the other rotation readers are — a manifest that cannot be
    read, or predates the field, contributes nothing.
    """
    from pipeline.reach import ROTATION_WINDOW

    here = Path(workspace).resolve()
    paths = {m.resolve() for m in here.glob("*manifest*.json")}
    base = Path(settings.workspace_dir)
    if base.is_dir():
        # This video's own workspace is read for `kept` even when a CLI
        # render put it outside `workspace_dir`.
        paths |= {m.resolve() for m in base.glob("*/*/*manifest*.json")}
    mine: list[tuple[float, str]] = []
    others: list[tuple[float, str]] = []
    for manifest in paths:
        try:
            room = json.loads(manifest.read_text(encoding="utf-8")).get(
                "cold_open_room")
            if not isinstance(room, str) or not room:
                continue
            row = (manifest.stat().st_mtime, room)
        except (OSError, ValueError, AttributeError):
            continue
        (mine if manifest.parent == here else others).append(row)
    others.sort(reverse=True)
    mine.sort(reverse=True)
    return ([r for _, r in others[:ROTATION_WINDOW]],
            mine[0][1] if mine else "")


def cold_open_segment(segments, duration: float,
                      until: float | None = None) -> int | None:
    """Index of the cold open's first shot of Dennis, or None.

    The first host beat still on screen once the opening title lifts — the
    title is opaque, so a wide room entirely under it is not a wide opening,
    and the first beat the viewer SEES him in is the one that establishes the
    room. Only inside the cold open (before `until`, the next chapter's
    start); None when he does not appear there at all.
    """
    title_end = min(INTRO_CARD_S, duration * 0.5)
    for i, seg in enumerate(segments):
        if until is not None and seg.start >= until:
            return None
        if seg.kind == "host" and seg.end - title_end > MIN_SEGMENT_S:
            return i
    return None


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

# How far AHEAD of the chapter opener a diegetic cue fires. Audio leading the
# visual makes a cue ANNOUNCE the image rather than react to it — the same
# reasoning as the record-scratch pre-roll on the first meme, which lands
# 0.35s before the freeze it is rewinding into. A hit lands on the frame
# instead; `sound.cue_lead_s` says which is which.
CHAPTER_CUE_LEAD_S = DEFAULT_LEAD_S


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
                      fps: int, ground: str) -> SegmentSpec | None:
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
                                       ",setsar=1,format=yuv420p[out]",
                                       ground=ground),
        layout="host-full",
        extra_identity=("fallback",),
    )


def _hold_still_chain(i: int, seg_len: float, W: int, H: int, tail: str, *,
                      ground: str) -> str:
    """A still, held: contain-fit onto the kit's ground, no movement at all.

    `ground` is the palette's `ground` as ffmpeg takes it (`0x171D2A`). The pad
    was a hard-coded paper white, the ground of the light kit two deliveries
    back, so a still that did not fill the frame sat between white bars in a
    night video.
    """
    return (
        f"[{i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={ground}{tail}"
    )


def _chapter_cues(stingers: list[dict], settings: Settings,
                  voicing: "Voicing | None" = None) -> list[AudioTrack]:
    """One cue per chapter opener that actually landed, or none at all.

    `CHAPTER_CUE_SFX` blank turns the whole thing off, and an unknown key is a
    warning and nothing else — the same contract as `[SOUND: …]`, because the
    alternative is a forty-minute render dying over a typo'd effect name.

    The default is `impact`, the hit a short lands on its first frame, which
    the operator chose over chapter music (2026-09-25). A hit fires ON the
    cut; the diegetic keys fire `CHAPTER_CUE_LEAD_S` ahead of it
    (`sound.cue_lead_s`). With a `voicing` each opener plays a different
    variant; the gain stays the staged one.

    Gain matches the meme boom (`sfx_gain_db + 2`). That number was chosen to
    sit ABOVE THE BED, and the bed is gone — the cue now lands in room tone
    with nothing competing with it, so the gain is worth re-auditioning
    against near-silence rather than against a drone.
    """
    key = (settings.chapter_cue_sfx or "").strip()
    if not key:
        return []
    if key not in EFFECT_KEYS:
        log.warning("CHAPTER_CUE_SFX=%r is not in the sfx library (%s) — "
                    "chapter openers get no cue", key, ", ".join(EFFECT_KEYS))
        return []
    path = settings.assets_dir / "sfx" / f"{key}.wav"
    if not path.exists():
        log.warning("CHAPTER_CUE_SFX=%r has no file at %s — chapter openers "
                    "get no cue", key, path)
        return []
    lead = cue_lead_s(key)
    out: list[AudioTrack] = []
    for s in stingers:
        t = max(float(s["t"]) - lead, 0.0)
        name = f"chapter_cue@{s['t']:.2f}"
        tr = voicing.fire(key, t, settings.sfx_gain_db + 2, name=name) \
            if voicing is not None else None
        out.append(tr or AudioTrack(path=path, start_s=t,
                                    gain_db=settings.sfx_gain_db + 2,
                                    name=name))
    return out


# A plate file's identity, for cache filenames that have to notice new art.
# Content-hashed rather than mtime'd: the kit is rebuilt by running an engine,
# so every ingest rewrites every file and an mtime would invalidate the whole
# cache on a build that changed nothing.
_PLATE_FINGERPRINTS: dict[tuple[str, int, float], str] = {}


def _plate_fingerprint(path: Path) -> str:
    """Eight hex characters of the plate file's content hash."""
    st = path.stat()
    ck = (str(path), st.st_size, st.st_mtime)
    got = _PLATE_FINGERPRINTS.get(ck)
    if got is None:
        import hashlib

        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        got = _PLATE_FINGERPRINTS[ck] = h.hexdigest()[:8]
    return got


def _played_clip(indices: list[int], frame_of: Callable[[int], Image.Image],
                 fps: int, dest: Path, *, reuse: bool = True) -> Path:
    """The frames `indices` name, each drawn once however often it shows.

    A room loop shows three pictures across twelve frames and a clip at 30 fps
    shows each of them ten times: drawing per output frame would resize the
    same 4K file thirty times a second of it. Written beside `dest` and moved
    into place, so a render stopped mid-encode leaves no clip for the next one
    to reuse half of.
    """
    if reuse and dest.exists():
        return dest
    drawn: dict[int, Image.Image] = {}
    for i in indices:
        if i not in drawn:
            drawn[i] = frame_of(i)
    part = dest.with_name(dest.stem + ".part" + dest.suffix)
    frames_to_alpha_clip([drawn[i] for i in indices], fps, part)
    os.replace(part, dest)
    return dest


# HOW LONG A CHAPTER OPENER IS ON SCREEN. A looping opener room is encoded to
# cover all of it, because a clip overlay that runs out mid-window vanishes.
CHAPTER_OPENER_S = 1.6


def _provenance(script, settings, workspace: Path, duration: float,
                seg_meta: list[dict], tts, *, draft: bool, proof: bool):
    """The render's provenance record (N3)."""
    from pipeline import provenance as prov
    from pipeline.filings import load_manifest

    prices = None
    if _reaches_a_price_chart_safe(script):
        from pipeline.prices import get_price_history

        ticker = (getattr(script, "ticker", "") or "").strip()
        if ticker:
            prices = get_price_history(ticker, settings)

    # `load_manifest` returns the WHOLE manifest — ticker, form, accession,
    # url and the shot list. Reading it as the shot list itself counted its
    # five top-level keys as five shots and then walked them as dicts, so a
    # workspace with any auto-pulled filing crashed this on `str.get`, after
    # the encode and the paid voice were already spent.
    shots = load_manifest(workspace).get("shots", []) or []
    filings = {"shots": len(shots)} if shots else {}
    refs = sorted({str(s.get("accession") or "") for s in shots
                   if s.get("accession")})
    if refs:
        filings["refs"] = [f"10-K {r}" for r in refs]
    brief = _filing_brief_provenance(workspace)
    if brief:
        filings["brief"] = brief

    fmt = "long-draft" if draft else "long-proof" if proof else "long"
    return prov.build(
        ticker=getattr(script, "ticker", ""), fmt=fmt,
        workdate=workspace.name, duration_s=duration,
        render={"engine": "segments"},
        prices=prices, visual_sources=_visual_source_counts(seg_meta),
        filings=filings, tts=tts, settings=settings)


def _reaches_a_price_chart_safe(script) -> bool:
    from pipeline.gates import _reaches_a_price_chart

    return _reaches_a_price_chart(script)


def _filing_brief_provenance(workspace: Path) -> dict:
    """What the pre-angle filing brief recorded about itself, if any.

    Written by the brief pass; absent before it has run. `context_held` is
    K2's question: a brief built from half a section reads exactly like one
    built from all of it.
    """
    import json as _json

    f = workspace / "filing_brief.json"
    try:
        data = _json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, _json.JSONDecodeError, OSError):
        return {}
    return {k: data[k] for k in ("sections", "context_held", "accessions")
            if k in data}


def _rendered_kit_reach(plate_keys: list[str], settings) -> str:
    """The reach line for a finished render, or "" when the kit is absent."""
    from pipeline.reach import reach_from_manifest

    reach = reach_from_manifest({"plates_used": plate_keys}, settings)
    return reach.line() if reach.keys else ""


def _visual_source_counts(seg_meta: list[dict]) -> dict[str, int]:
    """`{source: n}` over the segments that carried a fetched visual."""
    counts: dict[str, int] = {}
    for m in seg_meta:
        src = str(m.get("source") or "")
        if src:
            counts[src] = counts.get(src, 0) + 1
    return dict(sorted(counts.items()))


def _price_provenance(script, settings) -> dict:
    """`{source, degraded}` for a LONG that draws a price chart, else `{}`.

    Reads the same cached series the chart was drawn from, so it reports on
    the data that is actually in the video rather than on a fresh fetch that
    might disagree with it.
    """
    from pipeline.gates import _reaches_a_price_chart

    if not _reaches_a_price_chart(script):
        return {}
    ticker = (getattr(script, "ticker", "") or "").strip()
    if not ticker:
        return {}
    from pipeline.prices import get_price_history

    series = get_price_history(ticker, settings)
    return {"source": series.source, "degraded": bool(series.degraded)}


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

    At ONE HOUR, chosen here for the whole video and recorded on the manifest:
    every plate any module loads while this runs is drawn at it. See
    `plates.at_episode_hour`.
    """
    with at_episode_hour(settings, workspace, script.ticker):
        return _render_long(
            script, tts, workspace, settings, content,
            draft=draft, preview=preview, proof=proof,
            broll_overrides=broll_overrides, as_of=as_of,
            company_data=company_data, on_progress=on_progress)


def _render_long(
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
    """`render_long`, at the hour it has already fixed for the episode."""
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
    # The frame rate is decided BEFORE the plan, because the plan is what
    # snaps the cuts onto the frame grid (D1). Letting each encode round its
    # own `-t` independently is what put the picture ahead of the voice.
    fps = settings.preview_fps if preview else settings.fps
    segments, seg_warnings = plan_long_segments(
        cues, duration,
        chapter_starts=[(t, ti) for t, ti, _ in chapters],
        min_readable_s=settings.long_min_readable_s,
        chapter_host_s=settings.long_chapter_host_s,
        fps=fps,
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

    rdir = workspace / ("render_long_preview" if preview
                        else "render_long_draft" if draft
                        else "render_long_proof" if proof else "render_long")
    rdir.mkdir(parents=True, exist_ok=True)

    website = str(company_data.get("website") or "") if company_data is not None else ""
    overrides = broll_overrides or {}
    reg = load_plates(settings.assets_dir)
    aspect = "16x9"
    # The ground a held still is padded onto, as ffmpeg takes a colour.
    ground_ff = "0x" + reg.colour_hex("ground").lstrip("#")

    # THE WRITER'S MOVES, on the real clock. Each `[MOVE]` is paired with the
    # plate segment it acts on and timed off the spoken word; the list goes on
    # the manifest as `writer_moves` and on each plate segment's payload as
    # `moves`, which is where the move engine reads it while drawing the beat.
    writer_moves, move_warnings = plan_writer_moves(
        cues, segments, reg, chapter_starts=[t for t, _, _ in chapters])
    for w in move_warnings:
        log.warning("moves: %s", w)
    for m in writer_moves:
        segments[m.segment].payload.setdefault("moves", []).append(m.to_json())
    # WHAT PLAYED, AND WHEN: every move the render drew, in programme time,
    # with the beat and the slot — the same record a short writes, which is
    # what the sound is timed to. Filled as the beats are drawn.
    long_moves: list[dict] = []
    moves_skipped: list[str] = []
    # When each plate beat's moves have all landed, in programme time: the
    # source slides in after them, not over a figure still counting.
    seg_landed: dict[int, float] = {}
    # THE WRITER'S SOURCES, paired with their beats the same way (item 14).
    writer_sources, source_warnings = plan_writer_sources(cues, segments)
    for w in source_warnings:
        log.warning("sources: %s", w)
    moves_skipped.extend(source_warnings)

    # WHERE THE FRAME IS COVERED: the opening title, each chapter's bumper
    # (or the room opener on chapter one), and the wipes on the cold open and
    # the end. Worked out before the beats are drawn, so a beat that opens
    # under one holds its moves until it lifts.
    intro_dur = min(INTRO_CARD_S, duration * 0.5)
    chapter_cuts = _chapter_cuts(chapters, [s.start for s in segments],
                                 intro_dur=intro_dur, duration=duration)
    end_cut = max((s.start for s in segments if s.start > intro_dur + 2.0),
                  default=None)
    _bumper = reg.get(reg.aspect_key("structure/chapter-bumper", aspect) or "")
    _wipe_on, _wipe_off = 3 / 12, 4 / 12      # design's cut is under frame 4 of 8
    covers: list[tuple[float, float]] = [(0.0, intro_dur + _wipe_off)]
    if end_cut is not None:
        covers.append((end_cut - _wipe_on, end_cut + _wipe_off))
    for k, t in enumerate(chapter_cuts, start=1):
        if t is None:
            continue
        hold = (float(_bumper.hold_s or 2.0) if k > 1 and _bumper is not None
                else CHAPTER_OPENER_S)
        covers.append((t - _wipe_on, t + hold))

    px = lambda v: int(round(v * W / 1920))  # noqa: E731  (1920-wide design)

    def progress(done: int, total: int) -> None:
        log.info("segments %d/%d", done, total)
        if on_progress is not None:
            on_progress(done, total)

    # ------------------------------------------------ per-segment inputs
    inputs: list[str] = []
    lines: list[str] = []
    seg_meta: list[dict] = []
    plates_used: set[str] = set()

    # THE ROOM IS THE BOTTOM LAYER OF EVERY SHOT. It replaces the designed
    # filler backdrop, which existed because the old kit shipped no set: a beat
    # with no media got a generated card with the chapter's name printed on it.
    # There is a real room now, in nine angles, and a beat with nothing else in
    # it is simply the room.
    room_cache: dict[tuple[str, str], Path] = {}
    # WHAT THE LAST FEW VIDEOS ALREADY LOOKED LIKE (02): a preference to shoot
    # this one somewhere else, including at a different hour, wherever the kit
    # has somewhere else to offer. Empty on a fresh install, so nothing about
    # a first render changes.
    from pipeline.reach import recent_plates

    # `exclude` is this video's own workspace: a resumed or re-run render
    # must not read its own last manifest and rotate away from itself.
    _avoid_recent = recent_plates(settings, exclude=workspace)

    # The cold open's first shot, and the wide room it is in (see
    # `cold_open_room`). Chosen once here so every pass of this video, and the
    # manifest, agree on it.
    cold_i = cold_open_segment(
        segments, duration,
        until=chapters[1][0] if len(chapters) > 1 else None)
    cold_room = None
    if cold_i is not None:
        _recent_opens, _kept_open = _recorded_cold_opens(settings, workspace)
        _opening = cold_open_room(reg, aspect, recent=_recent_opens,
                                  kept=_kept_open)
        if _opening:
            # THROUGH `room_for`, with every other angle of the role avoided,
            # so whatever else decides a room — the hour, the season — decides
            # this one too, rather than a second path that forgets to ask.
            _role = opener_role(reg)
            cold_room = reg.room_for(
                _role, aspect, seed=script.ticker, episode=script.ticker,
                avoid=[k for k in reg.angles_for(_role, aspect, reg.hour)
                       if reg.base_key(k) != reg.base_key(_opening)])

    def _scene_in_force(t: float) -> dict | None:
        """The writer's scene as `{room, pose}` at programme time `t`, or None."""
        c = scene_in_force(cues, t)
        return dict(c.payload.get("values") or {}) if c is not None else None

    def _scene_room(scene: dict | None):
        """The room the writer's [SCENE] named, at this episode's hour and
        season; None when the beat is not directed or the kit lost the room.

        By its key, not by a role: the writer named the angle, so nothing
        here rotates it. The hour and the December twin still apply, because
        they are the episode's and not the writer's.
        """
        stem = (scene or {}).get("room") or ""
        key = reg.aspect_key(stem, aspect) if stem else None
        if key is None:
            if stem:
                log.warning("scene: the kit has no %s at %s — the bot picks "
                            "the room", stem, aspect)
            return None
        return reg.plate_at(key, reg.hour_for(script.ticker,
                                                 avoid=_avoid_recent))

    # THE WRITER OPENS THE VIDEO WHEN HE NAMES THE FIRST SCENE: the cold
    # open's first beat is shot where he put it, and recorded as the room it
    # opened in, so the next video's turn on the wide rooms still reads true.
    if cold_i is not None:
        _opened = _scene_room(segments[cold_i].payload.get("scene"))
        if _opened is not None:
            cold_room = _opened

    def _room_plate(role_name: str = "talk", seed: str = ""):
        # THE TICKER IS THE EPISODE, and it is passed separately from the seed
        # on purpose. Every caller below mixes a variant or a chapter title
        # into `seed` so consecutive rooms differ — which is right for the
        # ANGLE and wrong for the HOUR. `episode` is the ticker alone, so the
        # set stays at one hour for the whole video while the angle rotates.
        return reg.room_for(role_name, aspect, seed=seed or script.ticker,
                            episode=script.ticker, avoid=_avoid_recent)

    def _room_still(variant: int, role_name: str = "talk") -> Path:
        """The room, as a still. The bottom layer when nothing else is on.

        `_room_plate` raises when nothing fills the role, and that is the
        point: this used to paint a flat colour instead, which is how every
        two-shot in the format went weeks with no room in it.
        """
        return _room_file(_room_plate(role_name,
                                      seed=f"{script.ticker}|{variant % 3}"))

    def _room_file(plate) -> Path:
        """A room plate rasterised at the frame's size, once per video."""
        plates_used.add(plate.key)
        key = (plate.key, "")
        if key not in room_cache:
            # The cache filename carries a hash of the SOURCE PLATE (D3).
            # Keyed on the plate NAME alone, a workspace kept its pre-ingest
            # art forever: rebuild the kit with new room drawings, re-render,
            # and the file was already there so the old one was reused. The
            # ingest looked like it had done nothing.
            dest = rdir / f"room_{plate.name}_{_plate_fingerprint(plate.path)}.png"
            if not dest.exists():
                Image.open(plate.path).convert("RGB").resize(
                    (W, H), Image.LANCZOS).save(dest)
            room_cache[key] = dest
        return room_cache[key]

    def _loop_of(plate, files: list[Path], kind: str, mode: str) -> Path:
        """One pass of a looping room's `files` at the frame's size and rate.

        One pass is `frame_count / fps` seconds — one second for the kit's
        twelve frames at twelve — and the segment demuxer-loops it for as
        long as the beat holds, so no frame is decoded twice or held in
        memory. Keyed on the frames' content, like `_room_file`, so a new
        ingest is a new clip, and on the weather, which shares the key.
        """
        import hashlib

        plates_used.add(plate.key)
        key = (plate.key, f"{kind}-loop-{plate.weather}")
        if key not in room_cache:
            stamp = hashlib.sha256("|".join(
                _plate_fingerprint(f) for f in files).encode()).hexdigest()[:8]
            weather = f"_{plate.weather}" if plate.weather else ""
            dest = rdir / f"{kind}loop_{plate.name}{weather}_{stamp}_{fps}.mov"
            room_cache[key] = _played_clip(
                frame_indices(plate, playback_seconds(plate), fps),
                lambda i: Image.open(files[i]).convert(mode).resize(
                    (W, H), Image.LANCZOS),
                fps, dest)
        return room_cache[key]

    def _room_loop(plate) -> Path | None:
        """A room that keeps moving behind him, as a clip; None if it is still.

        THE ROOM LOOPS ARE BAKED INTO THE ROOM'S FRAMES (item 19): a screen
        that dips, a lamp that flickers, bulbs, snow or rain in the window.
        Held on its base file the room is frame one of that loop, frozen.
        """
        if not plate.animated or plate.plays_once:
            return None
        return _loop_of(plate, plate.frame_paths(), "room", "RGB")

    def _front_loop(room) -> Path | None:
        """The room's front layer as a clip, where its frames differ; or None.

        The flicker is mostly on the desk in front of him — the monitor and
        the lamp — so a front held still over a moving room paints the
        flicker out exactly where it shows.
        """
        if not room.animated or room.plays_once:
            return None
        fronts = [room.front_path(i) for i in range(len(room.frames))]
        if any(f is None or not f.exists() for f in fronts) \
                or len({str(f) for f in fronts}) < 2:
            return None
        return _loop_of(room, fronts, "front", "RGBA")

    def _front_file(room) -> Path | None:
        """The room's FRONT layer at the frame's size, or None.

        The desk he stands behind, drawn after him. A rebuild room is the
        whole room plus this layer: he goes between them, and pasting him over
        the whole room put the desk behind his legs.
        """
        src = front_of(room)
        if src is None:
            return None
        key = (room.key, "front")
        if key not in room_cache:
            dest = rdir / f"front_{room.name}_{_plate_fingerprint(src)}.png"
            if not dest.exists():
                Image.open(src).convert("RGBA").resize(
                    (W, H), Image.LANCZOS).save(dest)
            room_cache[key] = dest
        return room_cache[key]

    def _chapter_opener(title: str, seg_i: int, at: float | None = None) -> Path:
        """A chapter opener is THE ROOM WITH THE TITLE IN ITS SLOT.

        Not a separate stinger family. The old path drew a full-frame card from
        a hardcoded list of six section names and a baked ordinal, so a chapter
        could not be moved, repeated or cut without the card lying about it.
        """
        from pipeline.plate_frames import render_still

        # THE OPENER ROLE, where the kit publishes one: the rooms with a
        # `title` slot and the card drawn under it (desk-wide since rebuild-21,
        # window-wide since rebuild-39; board-wide has one too and is held back).
        # `establish` also holds rooms with no slot, and a pick of one of those
        # was a chapter whose title silently never reached the screen.
        role_name = opener_role(reg)
        # THE WRITER'S ROOM, when the scene he is in as the chapter opens is
        # one with a title slot: the card is that room with the title in it.
        # Any other room cannot carry the title, so the opener role picks.
        plate = next((p for p in [_scene_room(_scene_in_force(at))]
                      if p is not None and "title" in p.slots), None) \
            if at is not None else None
        plate = plate or _room_plate(role_name, seed=f"{script.ticker}|{title}")
        if "title" not in plate.slots:
            log.warning("chapters: %s has no title slot, so %r is not on "
                        "screen", plate.key, title)
            return _room_still(seg_i, role_name)
        plates_used.add(plate.key)
        if plate.animated and not plate.plays_once:
            # A LOOPING OPENER IS A CLIP, the title set on each picture of
            # the loop once. The opener angles are the wide ones, with the
            # window in shot, so this is where the snow and the rain are
            # seen; held on a still they would stop for the one shot that
            # shows them best.
            from pipeline.plate_frames import render_frame

            values = {"title": title}
            return _played_clip(
                frame_indices(plate, CHAPTER_OPENER_S + 0.5, fps),
                lambda i: render_frame(plate, i, values, settings, reg)
                .convert("RGB").resize((W, H), Image.LANCZOS),
                fps, rdir / f"chapter_{seg_i}.mov", reuse=False)
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

        plates_used.add(plate.key)
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
        # THE DATA GOES ON EVERY FRAME. Every chart, walk and rail in the
        # rebuild boils, so every one of them took this branch — and this
        # branch drew the type and never the data, which put every chart in a
        # long video on screen as an empty form. Drawn once, laid on each.
        data = declared_layer(reg, plate, values, seed=f"{plate.key}|{seg_i}")
        frames = []
        for idx in range(plate.frame_count):
            img = render_frame(plate, idx, values, settings, reg)
            if data is not None:
                img.alpha_composite(data)
            frames.append(img.resize((W, H), Image.LANCZOS))
        dest = rdir / f"plate_{seg_i}_{plate.name[:24]}.mov"
        frames_to_alpha_clip(frames, max(plate.fps or 2, 1), dest)
        return dest, True, (W, H), tuple(plan), plate.key

    # ------------------------------------------------ foreign media, framed
    # [CLIP], [IMG], [SHOW FILING] and [SCREENGRAB] land INSIDE a frames/
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
        plates_used.add(frame.key)
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
        return _hold_still_chain(input_i, seg_len, W, H, tail, ground=ground_ff)

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

    # THE LINE A CHAPTER RESTS ON IS TOLD IN CLOSE-UP. Every host beat in this
    # format was a full figure in a wide room — the shot you use when the ROOM
    # is the point — including the one the chapter is built to arrive at. The
    # last host beat before the next chapter starts is that line, and the kit
    # has a role for it: `rests-on` is the close-up.
    lands_a_chapter: set[int] = set()
    _bounds = [t for t, _title, _type in chapters] + [duration + 1.0]
    for _a, _b in zip(_bounds, _bounds[1:]):
        inside = [i for i, sg in enumerate(segments)
                  if sg.kind == "host" and _a <= sg.start < _b]
        if inside:
            lands_a_chapter.add(inside[-1])

    # THE CLOSE, as far as casting him goes: the last beat of the final
    # chapter he STANDS in. The line the chapter rests on is the close-up
    # above, and a framing is never cast — so the sign-off pose goes on the
    # standing beat before it, which is the last time he is seen whole.
    _last_from = chapters[-1][0] if chapters else 0.0
    closing_beat = max((i for i, sg in enumerate(segments)
                        if sg.kind == "host" and sg.start >= _last_from
                        and i not in lands_a_chapter), default=-1)

    def _words_in(seg) -> list:
        """The words said during a segment: what casts the pose he stands in."""
        return [w for w in tts.words if seg.start <= w.start < seg.end]

    def _shown_before(seg_i: int) -> str:
        """The pose the last beat before this one showed him in, if any."""
        shown = {int(m["segment"]): str(m.get("pose", ""))
                 for m in host_motion if "segment" in m}
        shown.update(panel_hosts)
        earlier = [k for k in shown if k < seg_i]
        return shown[max(earlier)] if earlier else ""

    # What the face did, per segment. Over forty minutes the host is the
    # most-viewed element in the channel and the easiest to leave static
    # without noticing, so the manifest records it.
    host_motion: list[dict] = []

    # What each directed beat was shot as, against what the writer asked:
    # the manifest's `scenes`, so a pose that fell back is findable.
    scene_meta: list[dict] = []

    def _scene_pose(scene: dict | None, room, seg_i: int) -> tuple[str | None, bool]:
        """(the writer's pose for this beat or None, whether it is the room alone).

        The room alone where nobody can stand in it — the board, the desk from
        above — unless he is in close-up, which is a camera distance and
        stands nowhere. A pose the kit caps (head-in-hands, once a video) that
        has had its turn falls back to the bot's pick, and says so.
        """
        if not scene:
            return None, False
        from pipeline.scenes import is_framing, pose_spec, stands_in

        asked = scene.get("pose") or ""
        plate = reg.get(asked) if asked else None
        framed = plate is not None and is_framing(plate)
        row = {"segment": seg_i, "room": reg.base_key(room.key), "asked": asked}
        scene_meta.append(row)
        if not stands_in(room) and not framed:
            row["shot"] = "room alone"
            return None, True
        if asked and plate is None:
            row["shot"] = "bot's pick: the kit does not draw that pose"
            log.warning("scene: %s is not in the kit — the bot picks his pose",
                        asked)
            return None, False
        limit = pose_spec(reg, asked).get("limit") if asked else None
        shown = sum(n for k, n in host_used.items() if reg.base_key(k) == asked)
        if limit and shown >= int(limit):
            row["shot"] = f"bot's pick: {asked} is used at most {int(limit)} a video"
            log.warning("scene: %s is capped at %d a video — the bot picks "
                        "his pose on the beat at %.1fs", asked, int(limit),
                        segments[seg_i].start)
            return None, False
        row["shot"] = asked or "bot's pick: the scene names no pose"
        return (asked or None), False

    def _host_input(seg_i: int, seg, seg_len: float, *, room,
                    panel: bool = False, pose: str | None = None):
        """Add the host clip as an input.

        Returns (index, x, y, w, h, front) or None, where `front` is the
        room's front layer when he is standing in it — the caller lays it
        over him — and None when he is framed or the room has no front.

        The room this beat is shot in decides his size and where he stands,
        and it is the CALLER'S room: this used to pick its own with a seed of
        the segment number while the background was picked with the beat's
        variant, so on two beats in three he was placed on one angle and
        drawn over another.

        `pose` is the WRITER'S, off his [SCENE]: taken as given, never cast
        from the words and never swapped for the close-up a chapter rests
        on. The role is only what he falls back to if the kit cannot draw it.
        """
        role_name = ("panel" if panel
                     else "beat" if pose
                     else "rests-on" if seg_i in lands_a_chapter
                     else "beat")
        # A STANDING BEAT MAY BE CAST BY ITS WORDS — a count on his fingers,
        # a shrug on the "but", the filing held up — where the room is one
        # the pose was drawn for. The close-up is a camera distance and is
        # never cast; with no cast the role picks, exactly as before.
        cast = (cast_pose(reg, _words_in(seg), room=room,
                          closing=seg_i == closing_beat, used=host_used,
                          avoid=_avoid_recent, previous=_shown_before(seg_i),
                          seed=f"{script.ticker}|{seg_i}")
                if role_name == "beat" and not pose else None)
        chosen = pose or (cast.pose if cast else None)
        # He is composited per output frame, so he is loaded at the size he
        # will be SHOWN at rather than at his delivered 2160x3840. Without
        # this every frame of every host beat is a 4K RGBA resize.
        shot_probe = ((host_shot(reg, chosen) if chosen else None)
                      or pick_shot(reg, role_name, seg_i, used=host_used))
        target_h = H
        if shot_probe is not None and shot_probe.is_framing:
            spot_probe = frame_shot(shot_probe, (W, H))
            if spot_probe is not None:
                target_h = max(spot_probe.height, 1)
        elif (room is not None and shot_probe is not None
                and stands_on(room, shot_probe)):
            placed_probe = place_on_room(room, shot_probe)
            target_h = max(int(placed_probe.height * (W / room.delivered[0])), 1)
        motion: dict = {}
        built = build_host_clip(
            tts.words, seg.start, seg.end, rdir / f"host_{seg_i}.mov",
            reg=reg, settings=settings, fps=fps, display_h=target_h,
            role=role_name, shot_index=seg_i, used=host_used, report=motion,
            pose=chosen,
        )
        if built is None:
            return None
        if motion:
            # Which cue cast him, when one did and the cast pose is what was
            # built — so a count that never reaches the screen is findable.
            motion["cast"] = (cast.cue if cast and reg.base_key(
                motion.get("pose", "")) == cast.pose else "")
            # And whether the writer's own pose is the one that was built.
            motion["directed"] = bool(pose) and reg.base_key(
                motion.get("pose", "")) == pose
            host_motion.append({"segment": seg_i, **motion})
            plates_used.add(motion.get("pose", ""))
            host_used[motion.get("pose", "")] = (
                host_used.get(motion.get("pose", ""), 0) + 1)

        clip_path, (hw, hh) = built
        # The pose the clip was actually BUILT from, not a second guess at it:
        # `build_host_clip` reads the same `used` tally this call just moved.
        shot = (host_shot(reg, motion.get("pose", "")) if motion else None) \
            or pick_shot(reg, role_name, seg_i, used=host_used)
        if shot is not None and shot.is_framing:
            spot = frame_shot(shot, (W, H))
            if spot is not None:
                return (_add_input(["-i", str(clip_path)]),
                        spot.x, spot.y, max(spot.width, 1),
                        max(spot.height, 1), None)
        if room is not None and shot is not None and stands_on(room, shot):
            placed = place_on_room(room, shot)
            k = W / room.delivered[0]
            return (_add_input(["-i", str(clip_path)]),
                    int(placed.x * k), int(placed.y * k),
                    max(int(placed.width * k), 1),
                    max(int(placed.height * k), 1), _front_file(room))
        return (_add_input(["-i", str(clip_path)]),
                int((W - hw) / 2), max(H - hh, 0), hw, hh, None)

    def _scaled_overlay_chain(bg_i: int, fg_i: int, x: int, y: int,
                              w: int, h: int, seg_len: float, tail: str, *,
                              loop: bool = False,
                              front_i: int | None = None) -> str:
        """A layer over the room, scaled into its box, as one concat-ready
        segment stream.

        `loop` is what a BOIL needs. A three-drawing boil is encoded once at
        its own 3fps and then repeated for the beat; cloning its last frame
        instead — which is what `tpad` does — freezes the drawing after a second,
        and a frozen plate beside a boiling room is the exact thing the boil
        exists to prevent.

        `front_i` is a full-frame still laid over the result — the room's
        front layer, so the desk he stands behind is in front of him.
        """
        fg = (f"[{fg_i}:v]loop=loop=-1:size=32767:start=0,setpts=N/FRAME_RATE/TB,"
              f"trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,scale={w}:{h}[hfg];"
              if loop else
              f"[{fg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
              f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
              f"trim=0:{seg_len:.4f},scale={w}:{h}[hfg];")
        if front_i is not None:
            return (
                f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}[hbg];"
                + fg +
                f"[{front_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"format=rgba,scale={W}:{H}[hfr];"
                f"[hbg][hfg]overlay={x}:{y}:eof_action=repeat[hmid];"
                f"[hmid][hfr]overlay=0:0:eof_action=repeat"
                f"{tail}"
            )
        return (
            f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}[hbg];"
            + fg +
            f"[hbg][hfg]overlay={x}:{y}:eof_action=repeat"
            f"{tail}"
        )

    def _moving_plate_chain(bg_i: int, mv_i: int, ld_i: int | None, x: int, y: int,
                            w: int, h: int, seg_len: float, tail: str,
                            landed_at: float) -> str:
        """A plate beat with its moves: the moves until they land, then the
        landed plate — held if it is a still, its boil looped if it boils.

        The landed loop is switched on under the moves' last frame, which
        already shows everything landed, so there is no frame between them.
        """
        bg = (f"[{bg_i}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
              f"scale={W}:{H}[hbg];")
        mv = f"[{mv_i}:v]setpts=PTS-STARTPTS,scale={w}:{h}[hmv];"
        if ld_i is None:
            return (bg + mv + f"[hbg][hmv]overlay={x}:{y}:eof_action=repeat{tail}")
        ld = (f"[{ld_i}:v]loop=loop=-1:size=32767:start=0,setpts=N/FRAME_RATE/TB,"
              f"trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,scale={w}:{h}[hld];")
        return (bg + ld + mv
                + f"[hbg][hld]overlay={x}:{y}:eof_action=repeat:"
                  f"enable='gte(t,{landed_at:.4f})'[hmid];"
                + f"[hmid][hmv]overlay={x}:{y}:eof_action=pass{tail}")

    def _plate_moves(seg, seg_i: int, key: str | None, seg_len: float):
        """The beat's moves drawn into clips, or None when it has none.

        The writer's `[MOVE]`s on this beat, and the chart's data drawing on
        as it arrives. Recorded in programme time for the manifest.
        """
        from pipeline.moves import plan_segment, render_segment

        plate = reg.get(key) if key else None
        if plate is None:
            return None
        values = dict(seg.payload.get("values") or {})
        rows = list(seg.payload.get("moves") or [])
        shot_id = f"segment_{seg_i}"
        moves, skipped = plan_segment(
            plate, values, rows, seg_len=seg_len, shot_id=shot_id, layer=shot_id,
            earliest=_cleared(seg.start, covers) - seg.start,
            settings=settings, reg=reg)
        moves_skipped.extend(skipped)
        for w in skipped:
            log.info("moves: %s", w)
        if not moves:
            return None
        clips = render_segment(plate, values, moves, seg_len=seg_len, size=(W, H),
                               settings=settings, reg=reg, out_dir=rdir,
                               stem=f"plate_{seg_i}", seed=f"{plate.key}|{seg_i}")
        if clips is not None:
            long_moves.extend({**m.row(), "start": round(seg.start + m.start, 3)}
                              for m in moves)
            seg_landed[seg_i] = seg.start + max(m.end for m in moves)
        return clips

    # ----------------------------------------------- the two-shot, on the room
    # A two-shot is the ROOM, the evidence, and Dennis standing beside it. It
    # used to be three finished designs stacked in one frame: a filler backdrop
    # with its own giant ticker and grid, the evidence card on top of that, and
    # a whole 16:9 host SLIDE over both, carrying its own headline and often its
    # own illustration. Every edge showed and two unrelated headlines argued
    # with each other and with the caption.
    #
    # One set. One piece of evidence. One cut-out standing in it.

    # One answer per beat. `_evidence_box`, `_fit_evidence` and `_panel_plate`
    # all ask, and `pick_shot` reads a `used` tally that a host beat in between
    # can move — which would size the evidence column against one pose and
    # composite another.
    panel_host_memo: dict[int, object] = {}

    def _panel_host(room, seg_i: int):
        """(shot, box, evidence side) for a two-shot, or None.

        A figure is placed by the room — the angle and its contact point say
        where he stands, and which side is left over follows from that.
        """
        if seg_i in panel_host_memo:
            return panel_host_memo[seg_i]
        picked = _solve_panel_host(room, seg_i)
        panel_host_memo[seg_i] = picked
        return picked

    def _solve_panel_host(room, seg_i: int):
        # THE TWO-SHOT IS A STILL, SO IT NEVER HOLDS A FRAMING. The evidence
        # beside him is pasted into one picture, and him with it: a close-up
        # held still for a beat is the closed mouth — a filled bar, which at
        # close-up scale reads as a dash — on screen for the whole of it.
        # design's crop review says never to cut close on a still (ANSWERS.md
        # §4, finding 2). A full figure is a still that reads: his mouth is a
        # few pixels at that size.
        shot = pick_shot(reg, "panel", seg_i, used=host_used, figures_only=True)
        if shot is None:
            return None
        # A ROOM THAT REFUSES A CUT-OUT TAKES NOBODY IN A TWO-SHOT. The angle
        # says nobody stands here; the only thing that could stand in for him
        # is the close-up, and a still two-shot may not hold one. So the
        # evidence has the frame.
        if room is None or not stands_on(room, shot):
            return None
        placed = place_on_room(room, shot)
        k = W / room.delivered[0]
        box = (int(placed.x * k), int(placed.y * k),
               max(int(placed.width * k), 1), max(int(placed.height * k), 1))
        # Whichever side of him has more room. He is placed by the ROOM, so
        # which side that is depends on the angle rather than on a flag.
        left_w = box[0] - px(120)
        right_w = W - (box[0] + box[2]) - px(120)
        side = "right" if right_w >= left_w else "left"
        # THE WORDS MAY CAST HIM HERE TOO — above all the hand held out to
        # the plate, which is only drawn reaching camera-right and so is cast
        # only when the evidence landed on that side of him. The evidence
        # column was sized against the role's pose, so a cast that would not
        # stand in exactly the same box is left out rather than re-solved.
        cast = cast_pose(reg, _words_in(segments[seg_i]), room=room,
                         plate_on=f"camera-{side}", used=host_used,
                         avoid=_avoid_recent, previous=_shown_before(seg_i),
                         seed=f"{script.ticker}|panel|{seg_i}")
        cast_shot = host_shot(reg, cast.pose) if cast else None
        if cast_shot is not None and stands_on(room, cast_shot):
            again = place_on_room(room, cast_shot)
            if (again.x, again.y, again.width, again.height) == (
                    placed.x, placed.y, placed.width, placed.height):
                shot = cast_shot
                # A cast pose keeps its `limit` across stills and talking
                # beats alike: the shrug is once a video, wherever it lands.
                host_used[shot.key] = host_used.get(shot.key, 0) + 1
        return (shot, box, side)

    def _evidence_box(room, seg_i: int, two_shot: bool) -> tuple[int, int, int, int]:
        """(x, y, max width, max height) for the evidence, beside the host."""
        if not two_shot:
            ew, eh = int(W * 0.86), int(H * 0.86)
            return int((W - ew) / 2), int((H - eh) / 2), ew, eh
        picked = _panel_host(room, seg_i)
        if picked is None:
            ew, eh = int(W * 0.86), int(H * 0.86)
            return int((W - ew) / 2), int((H - eh) / 2), ew, eh
        _shot, (hx, _hy, hw, _hh), side = picked
        if side == "right":
            right_w = W - (hx + hw) - px(120)
            return (hx + hw + px(60), int(H * 0.10),
                    max(right_w, px(400)), int(H * 0.80))
        return (px(60), int(H * 0.10),
                max(hx - px(120), px(400)), int(H * 0.80))

    def _fit_evidence(w: int, h: int, seg_i: int, *,
                      two_shot: bool) -> tuple[int, int]:
        """The size an evidence image of (w, h) takes in its column."""
        room = _room_plate("panel" if two_shot else "talk",
                           seed=f"{script.ticker}|{seg_i % 3}")
        _, _, max_w, max_h = _evidence_box(room, seg_i, two_shot)
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
        base = (Image.open(room.path).convert("RGB").resize((W, H), Image.LANCZOS)
                if room is not None
                else Image.new("RGB", (W, H), role(settings, "ground")))
        if room is not None:
            plates_used.add(room.key)
        bx, by, max_w, max_h = _evidence_box(room, seg_i, two_shot)
        ew, eh = size
        ex = bx + max(int((max_w - ew) / 2), 0)
        ey = by + max(int((max_h - eh) / 2), 0)
        picked = _panel_host(room, seg_i) if two_shot else None
        if picked is not None:
            shot, (hx, hy, hw, hh), _side = picked
            fig = Image.open(shot.pose.path).convert("RGBA").resize(
                (max(hw, 1), max(hh, 1)), Image.LANCZOS)
            base.paste(fig, (hx, hy), fig)
            # The desk he stands behind goes back on in front of him.
            front = _front_file(room) if room is not None else None
            if front is not None:
                layer = Image.open(front).convert("RGBA")
                base.paste(layer, (0, 0), layer)
            plates_used.add(shot.key)
            panel_hosts[seg_i] = shot.key
        base.save(dest)
        return dest, ex, ey

    # Where each beat's evidence actually landed in the frame. A plate in a
    # two-shot is not drawn at the full frame — it is shrunk into the room's
    # evidence column beside the host — so anything that has to line up with a
    # slot on it (an annotation solved onto a figure) needs this rect and not
    # the frame's. Recorded rather than recomputed, because `_fit_evidence`
    # and `_panel_plate` both depend on which room angle and which host shot
    # the seed picked.
    panel_rects: dict[int, tuple[int, int, int, int]] = {}

    # Which pose stood in each two-shot. Recorded because a panel role that
    # only ever reaches one of its poses is a failure the suite cannot see:
    # it is not an error, it is nine identical beats, and the only place it
    # shows is here.
    panel_hosts: dict[int, str] = {}

    def _panel_frame(still: Path, seg_i: int, dest: Path, *,
                     two_shot: bool = True) -> Path:
        """The two-shot, as ONE composition: the room, the evidence, Dennis."""
        panel = Image.open(still).convert("RGBA")
        ew, eh = _fit_evidence(panel.width, panel.height, seg_i,
                               two_shot=two_shot)
        panel = panel.resize((ew, eh), Image.LANCZOS)
        bg, ex, ey = _panel_plate((ew, eh), seg_i, dest, two_shot=two_shot)
        panel_rects[seg_i] = (ex, ey, ew, eh)
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

    def _annotated(seg) -> bool:
        """Whether a mark lands on this beat."""
        return any(seg.start - 1e-6 <= c.t < seg.end for c in scribble_cues)


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
            #
            # A LOOPING source needs no padding: `_clip_input` demuxer-loops it
            # so the stream never runs out, and the `trim` below is the whole
            # job. `tpad` is then a no-op rather than a wrong answer.
            return (
                f"[{idx}:v]trim=0:{seg_len:.4f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={seg_len:.4f},"
                f"trim=0:{seg_len:.4f},scale={W}:{H}{tail}"
            )

        def _clip_input(visual) -> int:
            """A clip as an ffmpeg input, repeating when it is meant to.

            A gif is two seconds long and a `hold=4.5` is not; a source that
            repeats and then freezes for the back half of its beat has the
            same defect as the freeze-frame this whole path exists to avoid.
            `-stream_loop` does it at the demuxer, so nothing is buffered —
            the `loop` FILTER holds every decoded frame in memory, which is
            fine for a two-frame boil and is not fine for eight seconds of
            1080p.
            """
            args = ["-stream_loop", "-1"] if visual.loops else []
            return _add_input([*args, "-i", str(visual.path)])

        def _room_input(room) -> int:
            """The room as an input: its loop where it moves, else its still.

            Demuxer-looped like a gif, and trimmed to the beat by the chain
            that reads it, exactly as the still is.
            """
            loop = _room_loop(room)
            if loop is None:
                return _still_input(_room_file(room))
            return _add_input(["-stream_loop", "-1", "-i", str(loop)])

        def _front_input(room, still: Path) -> int:
            """The desk in front of him, moving with the room behind him."""
            loop = _front_loop(room)
            if loop is None:
                return _still_input(still)
            return _add_input(["-stream_loop", "-1", "-i", str(loop)])

        if seg.kind == "host":
            # Dennis is the default base frame: the room, then the talking rig
            # lip-synced to this segment's slice of the voice-over.
            visual = None
            variant = seg.payload.get("variant", 0)
            # ONE ROOM FOR THE BEAT: the one drawn behind him is the one he is
            # placed on, and the one whose desk is drawn in front of him.
            # THE WRITER'S, where a [SCENE] directs this beat; the bot's
            # rotation only where none does.
            scene = seg.payload.get("scene") or None
            room = _scene_room(scene) if scene else None
            if room is None:
                scene = None
                room = (cold_room if i == cold_i and cold_room is not None
                        else _room_plate("talk",
                                         seed=f"{script.ticker}|{variant % 3}"))
            pose, alone = _scene_pose(scene, room, i)
            bg_i = _room_input(room)
            host = (None if alone
                    else _host_input(i, seg, seg_len, room=room, pose=pose))
            if host is None:
                chain = _still_chain(bg_i, seg, seg_len, i, tail)
            else:
                host_i, hx, hy, hw, hh, front = host
                front_i = (_front_input(room, front)
                           if front is not None else None)
                chain = _scaled_overlay_chain(bg_i, host_i, hx, hy, hw, hh,
                                              seg_len, tail, front_i=front_i)
        elif seg.kind == "clip":
            # Footage plays inside a frames/ plate rather than edge to edge.
            # Raw and full-frame it destroys the drawn surface the rest of the
            # video is built on: thirty minutes of ink, then a 4K stock shot,
            # then back — two videos cut together.
            visual = content.resolve_clip(value, overrides.get(value, 0))
            frame_plate = _frame_plate(CueKind.CLIP)
            clip_i = _clip_input(visual)
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
                clip_i = _clip_input(visual)
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
            # AN ANNOTATED BEAT TAKES THE FRAME.
            #
            # A mark is solved onto the type it names, so how big it lands is
            # decided by how big that type is on screen — and a plate shrunk
            # into a two-shot's evidence column beside the host is drawn at
            # about half size. A strike on one figure there solves to a 2.6
            # unit stroke against a legible band of 3.2 to 26: a hairline, on
            # the one beat somebody thought was worth pointing at.
            #
            # Thickening every stroke in the kit would fix one layout's scale
            # by making the whole library heavier. If a mark is worth making,
            # what it points at should be large enough to carry it — so the
            # composition gives way, not the ink.
            two_shot = (seg.payload.get("layout") == "two-shot"
                        and not _annotated(seg))
            moving = _plate_moves(seg, i, key, seg_len) if size is not None else None
            if moving is not None:
                # The same composition as the plate without its moves: the
                # moves are drawn at the frame's size and scaled into the
                # evidence box exactly as the plate itself is.
                ew, eh = _fit_evidence(W, H, i, two_shot=two_shot)
                bg, ex, ey = _panel_plate((ew, eh), i, rdir / f"bg_{i}.png",
                                          two_shot=two_shot)
                panel_rects[i] = (ex, ey, ew, eh)
                bg_i = _still_input(bg)
                mv_i = _add_input(["-i", str(moving.moving)])
                ld_i = (_add_input(["-i", str(moving.landed)])
                        if moving.landed is not None else None)
                chain = _moving_plate_chain(bg_i, mv_i, ld_i, ex, ey, ew, eh,
                                            seg_len, tail, moving.landed_at)
                seg_animation = {"asset": key, "moves": True,
                                 "landed_at": round(moving.landed_at, 3),
                                 "boils": moving.landed is not None}
            elif is_video:
                # A boiling plate is an alpha clip, so the background it plays
                # on is the same composition a still gets pasted into.
                ew, eh = _fit_evidence(size[0], size[1], i, two_shot=two_shot)
                bg, ex, ey = _panel_plate((ew, eh), i, rdir / f"bg_{i}.png",
                                          two_shot=two_shot)
                panel_rects[i] = (ex, ey, ew, eh)
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
            if visual.loops:
                # A gif repeating to fill its hold leaves no trace in a still
                # frame of the output, so the manifest is the only place the
                # difference between "looping" and "frozen after 2s" is
                # legible without scrubbing the file.
                meta["loops"] = True
        else:
            meta["attribution"] = ""
        if seg.kind == "host":
            meta["variant"] = seg.payload.get("variant", 0)
        if seg.payload.get("layout"):
            # WHAT WAS DRAWN, NOT WHAT WAS ASKED FOR. An annotated beat is
            # forced to the full frame whatever the script wrote, so a
            # manifest that echoed the payload said `two-shot` about a beat
            # rendered one-up — and the mark warnings are read against this.
            meta["layout"] = seg.payload["layout"]
            if seg.payload["layout"] == "two-shot" and _annotated(seg):
                meta["layout"] = "full-frame (annotated)"
                meta["layout_asked"] = "two-shot"
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
        if seg_animation and seg_animation.get("moves"):
            identity = (f"moves:{seg_animation['asset']}:{seg_animation['landed_at']}:"
                        f"{'boils' if seg_animation['boils'] else 'held'}",)
        elif seg_animation:
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
    # corner bug, disclaimer, captions, chapter bumpers, marks — composite
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
            fallback=lambda spec: _segment_fallback(spec, _backdrop_path, W, H, fps,
                                                    ground_ff),
            on_progress=progress,
            # Detection proves the GPU can open one encode session, not
            # `workers` of them at once. If it runs out partway through, the
            # run finishes on the CPU instead of dying.
            software_profile=profile.software_equivalent(settings),
        )
        base_video = concat_clips(seg_run.clips(), rdir / "base.mp4")
        # The cache lives outside the workspace so it survives cleanup, and
        # so nothing else bounds it: this run's clips stay, and the oldest of
        # the rest go once there are more than the cap.
        try:
            prune_cache(settings.cache_dir / SEG_CACHE_DIRNAME,
                        {p.stem for p in seg_run.clips()},
                        max_files=settings.segment_cache_max_files)
        except OSError as e:
            log.warning("segment cache: could not prune (%s)", e)
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
    stinger_meta: list[dict] = []
    transition_meta: list[dict] = []
    wipe_layers: list[OverlayLayer] = []

    def _wipe_at(cut: float, name: str, why: str) -> None:
        """A wipe with its full cover on `cut` (item 23), recorded."""
        clip = wipe_clip(reg, rdir / f"{name}_{len(transition_meta)}.mov",
                         name=name, aspect=aspect, cut=cut, size=(W, H))
        if clip is None or clip.end > duration:
            return
        # On top of everything, the bumper it opens on included: a wipe
        # that another layer cut across would show two shots at once.
        wipe_layers.append(OverlayLayer(path=clip.path, x=0, y=0,
                                        t_start=clip.start, t_end=clip.end,
                                        is_video=True, name=clip.name))
        transition_meta.append({"transition": name, "cut": round(cut, 3),
                                "start": round(clip.start, 3), "at": why})

    # THE COLD OPEN AND THE END ARE WIPED, sweep or page (item 23): the cut
    # off the opening title, and the cut into the video's last beat. Which of
    # the two is seeded per video, so the pair is not the same every time.
    import random as _random

    _pair = ["wipe-sweep", "wipe-page"]
    if _random.Random(f"wipes|{script.ticker}|{duration:.1f}").random() < 0.5:
        _pair.reverse()
    if intro_dur < duration - 1.0:
        _wipe_at(intro_dur, _pair[0], "cold open")
    if end_cut is not None and end_cut < duration - 1.0:
        _wipe_at(end_cut, _pair[1], "end")
    for k, ((target, title, ctype), t) in enumerate(zip(chapters, chapter_cuts), start=1):
        if t is None:
            log.warning("chapters: %r at %.0fs has no cut to land on — skipped",
                        title, target)
            continue

        # EVERY CHAPTER AFTER THE FIRST OPENS ON DESIGN'S BUMPER (item 22):
        # the number large and turning over from the last one, "OF SEVEN",
        # the title and the episode, held for the two seconds the plate
        # publishes, with the blinds closing over the cut into it (item 23).
        # Its number is counted off the script's own chapter list, so a
        # chapter moved or cut renumbers the rest; nothing is baked.
        # The first chapter keeps the room with its title in the slot: the
        # kit places the bumper between chapters, and the cold open has none.
        # Nothing fades in either, as design's rule 2 has it.
        bumper = None
        if k > 1:
            bumper = bumper_clip(
                reg, settings, rdir / f"bumper_{k}.mov", aspect=aspect, at=t,
                n=k, total=len(chapters), title=title,
                episode=f"{script.ticker.upper()} · {settings.brand_tagline.upper()}",
                size=(W, H))
        if bumper is not None:
            layers.append(OverlayLayer(
                path=bumper.path, x=0, y=0, t_start=t,
                t_end=min(bumper.end, duration), is_video=True, hold=True,
                name=f"chapter_{k}"))
            long_moves.append({"move": "tick-over", "start": round(tick_start(bumper), 3),
                               "shot_id": f"chapter_{k}", "slot": "num"})
            _wipe_at(t, "wipe-blinds", f"chapter_{k}")
        else:
            # A chapter opener is the room with the title in its slot, and a
            # room that loops (snow, rain, flicker) is a clip.
            cs_path = _chapter_opener(title, k, at=t)
            layers.append(OverlayLayer(
                path=cs_path, x=0, y=0, t_start=t,
                t_end=min(t + CHAPTER_OPENER_S, duration),
                is_video=cs_path.suffix == ".mov", name=f"chapter_{k}",
            ))
        stinger_meta.append({"type": ctype, "title": title,
                             "script_t": round(target, 2), "t": round(t, 2)})

    # THE SOURCE SLIDES IN UNDER THE FIGURE (item 14): design's tag, off the
    # frame's left edge with its small overshoot, where the writer's
    # [SOURCE] says, once the beat's moves have landed and nothing covers
    # the frame, held to the end of the beat. A beat too short to read it
    # after all that gets none, and the manifest says so.
    from pipeline.moves import TAG_READ_S, Move as _Move, source_tag_clip

    source_meta: list[dict] = []
    for src in writer_sources:
        seg = segments[src.segment]
        where = f"[SOURCE: {src.text}] at {src.t:.1f}s"
        start = max(src.t, seg.start)
        if src.segment in seg_landed:
            start = max(start, seg_landed[src.segment] + 0.15)
        start = _cleared(start, covers)
        end = min(seg.end, duration)
        if start + TAG_READ_S > end:
            moves_skipped.append(f"{where}: the beat cuts at {end:.1f}s, too soon "
                                 f"after its moves land to read a source — skipped")
            continue
        clip = source_tag_clip(reg, settings, rdir / f"source_{src.segment}.mov",
                               text=src.text, plate=reg.get(src.plate),
                               aspect=aspect,
                               panel=panel_rects.get(src.segment, (0, 0, W, H)))
        if clip is None:
            moves_skipped.append(f"{where}: no source tag for {src.plate} — skipped")
            continue
        layers.append(OverlayLayer(
            path=clip.path, x=clip.x, y=clip.y, t_start=start, t_end=end,
            is_video=True, hold=True, name=f"source_{src.segment}"))
        long_moves.append(_Move("slide-in", f"segment_{src.segment}", "", "source",
                                start, clip.frames, "land").row())
        source_meta.append({**src.to_json(), "start": round(start, 3),
                            "end": round(end, 3)})

    # Annotations (TOP layer, riding over whatever segment shows).
    #
    # An annotation is drawn in ATTENTION and therefore SPENDS the frame's one
    # attention, which is why there is one family and no separate doodle layer.
    # [DOODLE] used to put a second procedural drawing in a corner on top of
    # whatever was already there — a second visual language, competing with the
    # thing it was meant to punctuate.
    # A MARK GOES ON WHAT IT NAMES.
    #
    # `[SCRIBBLE: strike-out -> 212]` names its target, and where the beat
    # underneath is a plate the kit knows exactly which box holds "212" — the
    # director wrote it into that slot. This was drawn dead centre at a fixed
    # 700x460 regardless, so a bracket meant for one percentile row landed
    # across the middle of the strip, over three other rows and the figures
    # beside them. A plate still is drawn at the full frame, so a slot's box
    # maps onto the frame by one ratio.
    plate_beats = [
        (s.start, s.end, reg.get(str(s.payload.get("value") or "")),
         dict(s.payload.get("values") or {}),
         panel_rects.get(i, (0, 0, W, H)))
        for i, s in enumerate(segments) if s.kind == "plate"
    ]

    def _row_band(plate, slot, box):
        """The row band a slot sits in, if the plate declares one.

        A MARK THAT GROUPS ROWS TAKES THE ROW. `[SCRIBBLE bracket-rows "10th"]`
        means bracket the row that reads 10th, and matching the string found
        the four glyphs instead — a bracket 110px wide around one cell, solving
        to a stroke a third of the legible floor. The peer strip declares
        `band-N` regions 1601 units across for exactly this, so the target is
        the band the matched slot falls in.
        """
        sx, sy, sw, sh = slot.scaled()
        for name, other in plate.slots.items():
            if other.is_text or not name.startswith("band-"):
                continue
            bx, by, bw, bh = other.scaled()
            if bx <= sx and by <= sy and bx + bw >= sx + sw and by + bh >= sy + sh:
                return (bx, by, bw, bh)
        return box

    def _target_box(t: float, target: str,
                    style: str = "") -> tuple[int, int, int, int] | None:
        """The frame box holding `target` at time `t`, or None."""
        want = " ".join(str(target).split()).lower()
        if not want:
            return None
        for start, end, plate, values, rect in plate_beats:
            if plate is None or not (start <= t < end):
                continue
            rx, ry, rw, rh = rect
            kx = rw / max(plate.delivered[0], 1)
            ky = rh / max(plate.delivered[1], 1)
            # An exact value first: on a timeline with six cells reading
            # "Durable growth", a substring match would take whichever the
            # director happened to write first.
            for match_exact in (True, False):
                for name, value in values.items():
                    slot = plate.slots.get(name)
                    if slot is None or not slot.is_text:
                        continue
                    got = " ".join(str(value).split()).lower()
                    hit = (got == want) if match_exact else (got and want in got)
                    if not hit:
                        continue
                    ink = drawn_box(plate, slot, str(value), settings, reg)
                    if ink is None:
                        continue
                    if SCRIBBLE_MARKS.get(style, ("", ""))[1] == "bracket":
                        ink = _row_band(plate, slot, ink)
                    x, y, bw, bh = ink
                    return (int(rx + x * kx), int(ry + y * ky),
                            max(int(bw * kx), 1), max(int(bh * ky), 1))
        return None

    # EVERY MARK, AND WHAT IT SOLVED TO. The band warning went to the log,
    # where nobody reads it: a hairline on the one beat somebody thought was
    # worth pointing at is invisible in a green suite and invisible in a
    # terminal that scrolled. It is a property of the cut, so it goes in the
    # manifest with the rest of them.
    mark_solves: list[dict] = []

    for k, c in enumerate(scribble_cues):
        parsed = parse_scribble_payload(c.payload["value"])
        if parsed is None:
            continue
        style, target = parsed
        hold = float(c.payload.get("hold", 2.0))

        placed = None
        drawn_style = style.value
        box = _target_box(c.t, target, style.value)
        if box is not None:
            fitted: dict = {}
            solved = solve_mark(settings, style.value, box, report=fitted)
            drawn_style = fitted.get("style", style.value)
            if solved is not None:
                (mx, my, mw, mh), mark_warnings = solved
                for warn in mark_warnings:
                    log.warning("scribble %r: %s", target, warn)
                if fitted.get("swapped"):
                    log.info("scribble %r: %s", target, fitted["swapped"])
                mark_solves.append({
                    "t": round(float(c.t), 2), "style": drawn_style,
                    "asked": style.value, "target": target, "on_screen": True,
                    "fitted": fitted.get("swapped", ""),
                    "warnings": list(mark_warnings)})
                # A mark draws outside what it wraps, so a solved canvas larger
                # than the frame is expected. Several times the frame is not:
                # that is a target so small the mark blew up around it, and a
                # centred mark is better than a 40-megapixel stroke.
                if 0 < mw <= W * 3 and 0 < mh <= H * 3:
                    placed = (mx, my, mw, mh)
        if placed is None:
            if box is None:
                log.info("scribble %r: nothing on screen carries it — centred",
                         target)
                mark_solves.append({
                    "t": round(float(c.t), 2), "style": style.value,
                    "target": target, "on_screen": False, "warnings": []})
            placed = (int((W - px(700)) / 2), int((H - px(460)) / 2),
                      px(700), px(460))
        mx, my, sw, sh = placed

        # The mark draws itself on, in attention, over the current frame.
        frames = mark_frames(settings, sw, sh, style=drawn_style, fps=fps,
                             draw_seconds=min(hold, 0.5),
                             seed=f"{script.ticker}|scr|{k}")
        if not frames:
            continue
        hold_frames = max(int(hold * fps) - len(frames), 0)
        frames = frames + [frames[-1]] * hold_frames
        clip = frames_to_alpha_clip(frames, fps, rdir / f"scribble_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=mx, y=my,
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

    # THE LOWER THIRD: design's strip, the ticker and the channel's line in
    # its slots, TOP-left where the plain-type strip used to run, clear of
    # the captions. It is a solid card, so it rides the beats of HIM and no
    # others: over a plate or a two-shot it would sit on the evidence's own
    # top-left corner, and over a chapter card on its title. It slides in
    # the first time, as design's slide-in has it, and cuts with the shot
    # after that. A ticker longer than design's slot falls back to the old
    # line of type, which runs the whole video.
    from pipeline.moves import lower_third_clip, lower_third_image

    lt_img = lower_third_image(reg, settings, ticker=f"${script.ticker}",
                               tagline=settings.brand_tagline.lower(),
                               aspect=aspect)
    if lt_img is not None:
        plates_used.add(reg.aspect_key("overlays/lower-third", aspect))
        lt_w = px(LOWER_THIRD_W)
        lt_size = (lt_w, max(int(lt_img.height * lt_w / lt_img.width), 1))
        lt_x, lt_y = px(LOWER_THIRD_AT[0]), px(LOWER_THIRD_AT[1])
        lt_clip = lower_third_clip(lt_img, rdir / "lower_third.mov",
                                   x=lt_x, y=lt_y, size=lt_size, reg=reg)
        lt_still = rdir / "lower_third.png"
        lt_img.resize(lt_size, Image.LANCZOS).save(lt_still)
        for n, (a, b) in enumerate(_on_him(segments, covers)):
            first = n == 0
            layers.append(OverlayLayer(
                path=lt_clip.path if first else lt_still,
                x=0 if first else lt_x, y=lt_y, t_start=a, t_end=b,
                is_video=first, hold=first, name="lower_third"))
            if first:
                long_moves.append({"move": "slide-in", "start": round(a, 3),
                                   "shot_id": "lower_third", "slot": "",
                                   "frames": lt_clip.frames})
    else:
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
    #
    # THERE IS NO BED, and this is where it used to be mixed in. It was three
    # sine waves and brown noise — sixty seconds of a G drone, looped for
    # forty minutes under every video — and a lo-fi bed under a dry finance
    # monologue is the convention this channel exists to be the opposite of.
    # Room tone already does the only job it was doing: stopping the digital
    # silence between words that gives a cut away as assembled.
    #
    # The setting that muted it under a chapter type went with it. With no bed
    # there is nothing to mute, and a setting that does nothing is worse than
    # no setting; the fade machinery it needed went too. If a licensed bed
    # ever arrives, reintroduce both then rather than leaving the corpse.
    #
    # THE MIX STILL REACTS TO STRUCTURE. The chapter cue below is keyed off
    # the openers rather than off the narration and reads `stinger_meta`,
    # which is what actually landed on screen — a chapter with no cut to land
    # on was skipped above, and a cue for an opener nobody sees would be a
    # sound with no picture.
    audio = [AudioTrack(path=tts.audio_path, gain_db=0.0, voice=True,
                        name="voice")]
    # The room, under everything, and now the whole floor of the mix. It is
    # diegetic — the desk at three in the morning he is sitting at — and it
    # is the room at the hour the set is drawn at (`sound.room_track`).
    room = room_track(settings, reg.hour)
    if room is not None:
        audio.append(room)
    # NO EFFECT PLAYS THE SAME WAY TWICE: each firing is a different variant,
    # a little off in pitch and level (`pipeline/sound.py`). Seeded by the
    # script, so every pass of this video sounds the same.
    voicing = Voicing(settings.assets_dir / "sfx", script.content_sha())
    # A chapter opener gets an audible cue. The opener is otherwise visual
    # only, held 1.6s, and a viewer who looks away misses that a new argument
    # started — so this is a navigation signpost, not atmosphere.
    audio += _chapter_cues(stinger_meta, settings, voicing)
    # DESIGN'S MOVES, HEARD: a ratchet under a count-up, a marker under the
    # writer's circle, the flip as the bumper's number turns over, each on
    # the frame design lands it on (`sound.MOVE_CUES`). Timed to the record
    # below, not worked out again. A swish runs under the cold open's and the
    # end's wipes; the blinds into a bumper already have the chapter's hit.
    hits_at = [float(s["t"]) for s in stinger_meta]
    audio += move_cues(
        [Move(r["move"], r["start"], r.get("shot_id", ""), r.get("slot", ""),
              int(r.get("frames") or 0))
         for r in long_moves],
        settings, voicing, cuts=[Cut("chapter", t, t) for t in hits_at])
    audio += wipe_cues([(float(w["start"]), float(w["cut"]))
                        for w in transition_meta if "transition" in w],
                       settings, voicing, clear_of=hits_at)
    banner = audio_banner(settings)
    if banner:
        log.warning("%s", banner)
    for c in cues:
        if c.kind is CueKind.SOUND and c.payload.get("value") in SFX_KEYS:
            key = c.payload["value"]
            tr = voicing.fire(key, c.t, settings.sfx_gain_db,
                              name=f"{key}@{c.t:.2f}")
            if tr is not None:
                audio.append(tr)
    # meme stings: boom on every meme; the FIRST meme gets the occasional
    # record-scratch rewind treatment
    meme_segs = [s for s in segments if s.kind == "meme"]
    for j, seg in enumerate(meme_segs):
        tr = voicing.fire("vine_boom", seg.start, settings.sfx_gain_db + 2,
                          name=f"vine_boom@{seg.start:.2f}")
        if tr is not None:
            audio.append(tr)
        if j == 0:
            tr = voicing.fire("record_scratch", seg.start - 0.35,
                              settings.sfx_gain_db,
                              name=f"record_scratch@{seg.start:.2f}")
            if tr is not None:
                audio.append(tr)
    # The channel theme: the intro under the cold open, the outro ending
    # with the video, both dipped under the voice. Never under a chapter:
    # the operator put a hit on the chapter change instead of music.
    audio += theme_tracks(settings, duration)

    layers += wipe_layers

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
    # Render beside the target, validate, then `os.replace` into position
    # (D2). `composite_video` used to write straight over the existing file
    # and the sanity check ran afterwards, so a failure at any point past
    # that line left the operator with nothing — not the new render and not
    # the good one they already had. A forty-minute build is a bad thing to
    # lose twice. `segments._encode_one` already worked this way.
    part = out_path.with_suffix(".part.mp4")
    part.unlink(missing_ok=True)
    composite_video(spec, profile, settings.audio_bitrate, part)

    rendered = ffprobe_duration(part)
    if abs(rendered - duration) > 0.7:
        part.unlink(missing_ok=True)
        raise RenderError(
            f"rendered duration {rendered:.2f}s deviates from the audio master "
            f"clock {duration:.2f}s"
        )
    os.replace(part, out_path)
    # `composite_video` writes its filtergraph beside its OUTPUT, so the
    # sidecar followed the temp name. Move it with the file it describes —
    # the manifest points at it, and the tests read it to check what was
    # actually drawn.
    part_filter = part.with_suffix(".filter.txt")
    if part_filter.exists():
        os.replace(part_filter, out_path.with_suffix(".filter.txt"))

    manifest_path = workspace / ("render_long_draft_manifest.json" if draft
                                 else "render_long_proof_manifest.json" if proof
                                 else "render_long_manifest.json")
    attributions = sorted({m["attribution"] for m in seg_meta
                           if m.get("attribution")})
    price_provenance = _price_provenance(script, settings)
    provenance = _provenance(script, settings, workspace, duration, seg_meta,
                             tts, draft=draft, proof=proof)
    audio_rows = manifest_rows(audio)
    # WHAT THE MIX DID, on the delivery message. Measured off the file, not
    # assumed from the graph; a draft is not worth the extra pass.
    provenance.sound = sound_summary(
        audio_rows, lufs=None if draft else measure_lufs(out_path),
        placeholders=placeholders_played(settings, audio))
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "draft": draft,
        "proof": proof,
        # THE HOUR THE SET IS AT, for the whole video. The next pass of this
        # video reads it back so a proof and its final cannot come out at two
        # different hours; see `plates.hour_of_episode`.
        "hour": reg.hour,
        # The audio tier, carried on the manifest so "is this shippable?" is
        # answerable from the artefact rather than from whoever ran it. A
        # proof is real pictures over a free voice: everything below is what
        # a final would have used, the voice is not.
        "audio_tier": getattr(tts, "tier", ""),
        "draft_audio": bool(getattr(tts, "draft", False)),
        # Where the numbers on any price chart came from, and whether they
        # are real (B1). Absent when the script draws no price chart.
        **({"prices": price_provenance} if price_provenance else {}),
        # THE WHOLE RECORD (N3): what in this video was real. Machine-
        # readable here, and the same thing in words on the delivery
        # message, so the two surfaces cannot drift.
        # WHICH ENGINE DREW IT (P4): this one for a LONG, the shot engine for
        # every SHORT, answerable from the artefact.
        "engine": "segments",
        "provenance": provenance.to_json(),
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
        # WHAT THE MIX ACTUALLY DID. A cue on every opener is a decision taken
        # from `stingers` below and it leaves no trace in the picture — so it
        # goes here, where the operator (and the suite) can read it without
        # opening the audio in something that draws waveforms.
        #
        # Named by SOURCE AND TIME, because the same file fires repeatedly: a
        # boom on every meme and a cue on every opener are several rows that
        # would otherwise be indistinguishable from one another.
        "audio": audio_rows,
        "marks": mark_solves,
        # Each [SOURCE] the writer wrote and when its tag slid in.
        "sources": source_meta,
        "marks_out_of_band": [m for m in mark_solves if m["warnings"]],
        "segment_warnings": seg_warnings,
        "chapter_warnings": chapter_warnings,
        # What the video actually announces, against what the script asked
        # for. Read this rather than trusting the suite: the stingers used to
        # be six hardcoded titles spaced evenly, and every test passed.
        "chapters": [{"t": round(t, 2), "title": ti, "type": ct}
                     for t, ti, ct in chapters],
        # THE WRITER'S [MOVE]s as the render should play them: move, plate
        # key, the kit's slot and box for it, programme time `t` and the time
        # `at` into its plate `segment`. See `timeline.WriterMove`.
        "writer_moves": [m.to_json() for m in writer_moves],
        "move_warnings": move_warnings,
        # The wide room the cold open's first shot was in, as a base key.
        # The next video reads it to take its turn on the other one, and the
        # next pass of THIS video reads it to open on the same one.
        "cold_open_room": (reg.base_key(cold_room.key)
                           if cold_room is not None else ""),
        # THE WRITER'S SCENES as they were shot: per directed beat of him,
        # the room, the pose he asked for and what was drawn — the pose, the
        # room alone, or the bot's pick and why.
        "scenes": scene_meta,
        # WHAT THIS RENDER ACTUALLY REACHED. The doctor diffs the library
        # against this across recent renders to answer "what have we drawn and
        # never used" — which is the gap list the next design batch is drawn
        # from, and it is worth nothing if nobody writes the numerator down.
        "plates_used": sorted(plates_used),
        # The render's own reach line, in the same shape as the script's, so
        # "how much of the kit did this actually use" is answerable from the
        # artefact (J3). `rendered_reach` existed for this and had no caller.
        "kit_reach": _rendered_kit_reach(sorted(plates_used), settings),
        "stingers": stinger_meta,
        "transitions": transition_meta,
        # EVERY MOVE THE LONG PLAYED, in the short's shape: design's move id,
        # the programme time of its first frame, the beat or chapter it was on
        # and the slot. The bumper's tick-over is here; the wipes list their
        # cut. This is what the sound is timed to.
        "moves": {"moves": sorted(long_moves, key=lambda r: (r["start"], r["move"])),
                  "wipes": [{"transition": w["transition"], "cut": w["cut"],
                             "start": w["start"]} for w in transition_meta
                            if "transition" in w],
                  "skipped": moves_skipped},
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
        # Who stood in each two-shot. A glance key here is the pipeline having
        # cut him toward the graphic rather than through it.
        "panel_hosts": panel_hosts,
        "glances": sorted({k for k in panel_hosts.values() if "-glance-" in k}),
        "blinks": sum(m.get("blinks", 0) for m in host_motion),
        "shots_with_blink": sum(1 for m in host_motion if m.get("has_blink")),
        "shots_with_idle": sum(1 for m in host_motion if m.get("has_idle")),
        "attributions": attributions,
        # Where every visual came from, counted (H3). `Visual.source` was
        # already exactly the right vocabulary — local | library | cache |
        # pexels | wikimedia | company_site | giphy | tenor | imgflip | mock
        # | generated | filler — and nothing counted it, so a video leaning
        # on user-uploaded GIF content left no trace anywhere.
        "visual_sources": _visual_source_counts(seg_meta),
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2), encoding="utf-8")
    return out_path, manifest_path
