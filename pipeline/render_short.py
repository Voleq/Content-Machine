"""SHORT scene engine — 9:16, ~60-75s "Noise or signal?" (§4).

DENNIS IS IN THIS VIDEO. That is the difference between this engine and the one
it replaces. The short never migrated when long-form did: it opened on a chart,
ran four fixed cards, and closed on a chart, reaching about six assets out of
three hundred and eighty-four. The timeline had been emitting `HOST_OPEN` and
`HOST_CLOSE` cues the whole time and nothing read them.

The frame, top to bottom:

  * the **light** kit, everywhere. The cards were inverted when the palette
    flipped; the backdrop, the napkin chart and the captions were not, so a
    short opened on paper, cut to a black chart and captioned it in red.
  * **host bookends** — Dennis on camera for the first and last few seconds,
    mouth-flapped to the voice-over, and back every four to five beats.
  * **two-shots** for evidence: him beside the thing being discussed, so the
    cut never leaves the person the viewer is watching.
  * the **full tag grammar** — `[IMG]`, `[PRODUCT]`, `[SHOW FILING]`,
    `[SHOW ARTICLE]`, `[SCREENGRAB]`, `[PROP]`, `[BIGNUM]`, `[TERM]`,
    `[MEME]`, `[CLIP]` claim the frame; `[DOODLE]`, `[SCRIBBLE]` and `[ALERT]`
    ride on top; `[BEAT]`, `[FLAT]`, `[SIGH]` and `[DRY]` never reach the
    screen at all and go to the voice instead.
  * a **motion layer** on arrival only: figures count up to the spoken word,
    charts and bars draw on, table rows type on, cards slide in, the payoff
    slams, captions punch.
  * artwork SIZED FOR THIS FRAME. A square or portrait drawing takes the
    frame's full width — 134 of the kit's assets are 1:1 and every one of them
    was being contain-fitted into a 1000x760 landscape box, so it covered 28%
    of a 1080x1920 screen and the whole video read as cards floating in paper.
    `render_short_manifest.json` records what fraction of the frame each beat
    actually occupies, so this stays a measurement rather than an opinion.

NOTHING PANS OR ZOOMS. The motion is in the frames now — 84 of the kit's assets
are real sequences — and drift on top of a registered strip makes the
registration itself look broken.

Every visual event's time comes from `build_short_timeline` and
`plan_short_pacing` (the master clock and the pacing contract); this module
turns cues into rasters, alpha clips and one FFmpeg filtergraph. There are NO
hardcoded scene timings here.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from config import Settings
from pipeline.broll import ContentManager
from pipeline.chart import render_marker_price_chart, render_price_chart
from pipeline.host import build_host_clip, pick_shot
from pipeline.kit import Kit, KitError, load_kit, load_variant_ledger
from pipeline.kit_frames import (
    FULL_BLEED,
    plate,
    PUNCH,
    STAGE,
    bind_slot_values,
    cover_on_paper,
    fit_into,
    is_full_frame,
    playback_seconds,
    punch_crop,
    render_clip,
    render_still,
    strip_baked_furniture,
    transition_asset,
    transition_transform,
)
from pipeline.number_beats import beat_for_row
from pipeline.vertical_beats import beat_for_row as vertical_beat_for_row
from pipeline.models import (
    KIT_TAG_BLANKS,
    KIT_TAG_FAMILIES,
    ChartStyle,
    CueKind,
    ShortScript,
    TTSResult,
    TagType,
    parse_scribble_payload,
)
from pipeline.prices import PriceSeries, get_price_history
from pipeline.rasters import (
    INK,
    RED,
    SHANTELL,
    build_phrase_ass,
    count_up_frames,
    doodle_clip,
    draw_on_frames,
    flash_frames,
    frames_to_alpha_clip,
    headline_card,
    lower_third,
    number_row_frames,
    numbers_sheet_base,
    scribble_callout_frames,
    scribble_frames,
    simple_text,
    slide_in_frames,
    stamp_slam_frames,
    text_panel,
    ticker_pill,
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
from pipeline.timeline import build_short_timeline, plan_short_pacing

log = logging.getLogger(__name__)


# The 9:16 plate the whole video sits on. Light, and never moving.
BACKDROP_KEY = "backgrounds/room-tall"

# The signature open and close: full-frame 9:16, four frames at 8fps, two
# slots each. Every short opens and closes on these — that is the point of
# them, and it is why they are addressed by key rather than picked.
OPEN_KEY = "shorts/open-close/e-open"
CLOSE_KEY = "shorts/open-close/e-close"

# The payoff card. Not a verdict stamp — the words carry the conclusion; this
# is the shape the channel ends on.
PAYOFF_CARDS = {"noise": "short/card-noise", "signal": "short/card-signal"}

# The desk set. Four 1:1 scenes, each declaring a `screen` box, and nothing had
# ever put anything in one. They give the video three plates instead of one
# flat backdrop held for its whole runtime — the open, the move, the payoff.
DESK_OPEN_KEY = "shorts/the-world/d-desk-wide"
DESK_CHART_KEY = "shorts/the-world/d-desk-over-shoulder"
DESK_PAYOFF_KEY = "shorts/the-world/d-desk-side"

# The room, for the stretch between the acts. The three keys above covered the
# open, the chart and the payoff; everything in between — the gut check, which
# is the longest section of the video — played on blank `room-tall`. A room
# with a desk in it reads as a place; blank paper reads as a missing asset.
#
# `d-desk-over-shoulder` is deliberately NOT here. It is a SHOT — the back of
# his head fills the lower third, framing the monitor — which is right when
# the beat is "he is looking at the chart" and oppressive as a backdrop held
# behind four other beats.
DESK_SET: tuple[str, ...] = (
    "shorts/the-world/d-desk-wide",
    "shorts/the-world/d-desk-side",
    "shorts/the-world/d-desk-empty",
)

# How long one backdrop holds before the room changes angle. Long enough that
# it is a place rather than a cut, short enough that a forty-second gut check
# is not one still.
DESK_ROTATE_S = 11.0

# --------------------------------------------------------------------------
# The vertical layout, in 1080-wide design coordinates on a 1080x1920 frame.
#
# A 9:16 frame is three bands, and the engine this replaces had no idea: every
# layer was placed independently and left up for the whole video, so the chart
# sat over the host, the sheet sat over the chart, and the payoff card sat
# under both. Naming the bands is what makes a beat able to REPLACE the one
# before it instead of piling on top of it.
#
#   FURNITURE   0 ..  140   the bug and the ticker pill. Always up.
#   HOOK      170 ..  330   the mute-safe opening line, ABOVE the artwork.
#   STAGE     230 .. 1310   whatever the beat is. Exactly one thing at a time:
#                           the host, the chart, the sheet, or a tag beat.
#   LEDGER   1340 .. 1560   the trap and the payoff line.
#   CAPTIONS 1560 .. 1800   the spoken word. Nothing else goes here.
#
# Vertical video reads text-top, action-centre, captions-bottom. This used to
# read text-bottom, action-middle, text-bottom: the stage started at 360 and
# ran 760 tall, so the top nineteen per cent of every frame was blank paper
# while the hook, the ledger and the captions all competed in the bottom
# third. The stage is taller and starts higher, and the hook has its own band
# above it.
# --------------------------------------------------------------------------
STAGE_Y = 230
STAGE_H = 1080        # tall enough that a 1:1 drawing gets the FULL frame width
HOOK_Y = 170          # the hook band, above the stage
LEDGER_Y = 1340
HOST_Y = 430          # the 16:9 shots are full-width; this centres them
INSET_Y = 1120        # the two-shot inset, clear of the ledger
INSET_W = 480         # ... and the column it reserves on the right
INSET_GAP = 28        # clear air between the inset and whatever sits beside it
INSET_MARGIN = 30     # the inset's own distance from the right edge
CAPTION_MARGIN_V = 150  # the caption band's distance from the bottom edge

# A data beat's box. A SQUARE or PORTRAIT drawing fits the frame's full width
# and takes whatever height it needs; only a landscape one is contain-fitted
# into a landscape box.
#
# The box was a flat 1000x760 for everything, so a 1:1 asset — 134 of them —
# contain-fitted to 760x760 and covered 28% of a 1080x1920 frame. Fitting the
# same drawing to width puts it at 1080x1080, 56%, and doubles its presence
# for nothing.
STAGE_MAX_W = 1080
PUNCT_BOX = 760       # was 520, which put a 1:1 reaction at 13% of frame —
                      # small enough to read as a sticker rather than a beat

# Per-beat layout variants from the design kit's Short Variants sheet. The
# timeline picks one per beat from the script hash, so two shorts cut on the
# same day do not share a layout while any single script always renders
# identically.
# The hook sits ABOVE the artwork. It used to render in the ledger band at
# 1150, under the stage, so the hook, the trap line and the captions all
# competed in the bottom third of the frame while the top fifth was blank.
HOOK_LAYOUTS: dict[str, dict] = {
    "a": {"y": HOOK_Y, "size": 60, "width": 960, "accent": RED},
    "b": {"y": HOOK_Y + 14, "size": 68, "width": 920, "accent": RED},
    "c": {"y": HOOK_Y + 26, "size": 54, "width": 980, "accent": INK},
    "d": {"y": HOOK_Y - 10, "size": 64, "width": 880, "accent": RED},
    "e": {"y": HOOK_Y + 6, "size": 62, "width": 940, "accent": INK},
}
NUMBERS_LAYOUTS: dict[str, dict] = {
    "a": {"y": STAGE_Y + 40, "width": 1060},
    "b": {"y": STAGE_Y, "width": 1080},
    "c": {"y": STAGE_Y + 80, "width": 1040},
    "d": {"y": STAGE_Y + 20, "width": 1060},
}
PAYOFF_LAYOUTS: dict[str, dict] = {
    "a": {"y": LEDGER_Y, "size": 48, "accent": INK},
    "b": {"y": LEDGER_Y + 30, "size": 52, "accent": RED},
    "c": {"y": LEDGER_Y - 20, "size": 46, "accent": INK},
    "d": {"y": LEDGER_Y + 10, "size": 50, "accent": RED},
    "e": {"y": LEDGER_Y + 50, "size": 44, "accent": INK},
}


def _layout(table: dict[str, dict], variant: str | None) -> dict:
    """The layout for a beat variant, falling back to the original."""
    return table.get(variant or "a", table["a"])


def sample_hook_opener(script_sha: str, settings: Settings) -> str:
    """Deterministically sample the hook bank (seeded by the script sha so
    re-renders are idempotent, different scripts get fresh openers)."""
    bank_file = settings.assets_dir / "hook_bank.json"
    try:
        openers = json.loads(bank_file.read_text(encoding="utf-8")).get("openers") or []
    except (FileNotFoundError, json.JSONDecodeError):
        openers = []
    if not openers:
        return settings.brand_tagline
    idx = int(hashlib.sha256(f"hook|{script_sha}".encode()).hexdigest()[:8], 16)
    return openers[idx % len(openers)]


def payoff_card_key(conclusion: str) -> str:
    """Which closing card the payoff lands on.

    Read off the conclusion's own opening words, which the format requires to
    be the call muttered plainly. No taxonomy, no enum — if the text does not
    say "signal", it is the noise card, which is also the honest default.
    """
    head = conclusion.strip().lower()[:40]
    return PAYOFF_CARDS["signal" if "signal" in head and "noise" not in head
                        else "noise"]


def _kit_asset_for(kit: Kit, tag: TagType, key: str):
    """(asset, is_blank) for a card tag, or (None, False).

    Named artwork first, then the parameterised blank layout — which is how
    `[TERM: owner earnings]` gets a card at all when nobody has drawn one.
    """
    families = KIT_TAG_FAMILIES.get(tag)
    if families:
        asset = kit.resolve_asset(families, key)
        if asset is not None:
            return asset, False
    blank = KIT_TAG_BLANKS.get(tag)
    if blank:
        asset = kit.get(blank)
        if asset is not None:
            return asset, True
    return None, False


def _blank_values(tag: TagType, key: str, script: ShortScript,
                  values: dict[str, str] | None = None) -> dict[str, str]:
    """What goes in a blank layout's slots for a tag the kit has no art for.

    The tag's own `= value` wins where the writer gave one. Without it a
    `[BIGNUM: dilution]` had nothing to put in the figure box but the word
    "dilution", which it then repeated in the headline underneath — a card
    that says the same word twice and no number at all.
    """
    values = values or {}
    label = key.replace("-", " ").strip()
    given = next((v for k, v in values.items() if v), "")
    if tag is TagType.BIGNUM:
        return {"kicker": label,
                "figure": given or label,
                "headline": "" if given else script.move_summary,
                "context": script.move_summary if given else ""}
    return {"kicker": "the word of the day", "term": label.title(),
            "definition": given or script.numbers_comment}


def render_short(
    script: ShortScript,
    tts: TTSResult,
    workspace: Path,
    settings: Settings,
    *,
    content: ContentManager | None = None,
    prices: PriceSeries | None = None,
    out_name: str = "short_final.mp4",
) -> tuple[Path, Path]:
    """Render the SHORT. Returns (mp4_path, manifest_path)."""
    # A SHORT has no draft mode — it is a minute of video — so draft audio has
    # no business here at all. Same reason as the LONG: interpolated word
    # timings must never be the master clock of a published cut (P3.2).
    if getattr(tts, "draft", False):
        raise RenderError(
            f"refusing to render a SHORT from {tts.tier} draft audio — its "
            f"word timings are interpolated. Approve the script so the paid "
            f"voice runs first.")
    content = content or ContentManager(settings)
    prices = prices or get_price_history(script.ticker, settings)

    duration = tts.duration_s
    cues = build_short_timeline(script, tts.words, duration)
    cues, pacing_warnings = plan_short_pacing(cues, duration)
    for w in pacing_warnings:
        log.warning("short pacing: %s", w)
    for c in cues:
        if c.fallback:
            log.warning("cue %s used a fallback position (t=%.2fs)", c.kind.value, c.t)

    W, H = settings.short_resolution
    s = W / 1080.0  # design coordinates are 1080-wide

    def px(v: float) -> int:
        return int(round(v * s))

    rdir = workspace / "render_short"
    rdir.mkdir(parents=True, exist_ok=True)
    fps = settings.fps

    kit = load_kit(settings.assets_dir)
    # One ledger for the whole render: the auto-reached number beats consult it
    # while choosing, and every key that reaches the frame is recorded into it
    # at the end.
    beat_ledger = load_variant_ledger(settings)
    # The structural assets are required, not hoped for. A short that silently
    # loses its host or its backdrop is exactly the failure this rebuild is
    # for, and it passed every test it had.
    backdrop = kit.require(BACKDROP_KEY, why="the short's 9:16 plate")
    kit.require(OPEN_KEY, why="the signature open")
    kit.require(CLOSE_KEY, why="the signature close")

    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    host_open = next(c for c in cues if c.kind is CueKind.HOST_OPEN)
    host_close = next(c for c in cues if c.kind is CueKind.HOST_CLOSE)
    host_beats = [c for c in cues if c.kind is CueKind.HOST_BEAT]
    transitions = [c for c in cues if c.kind is CueKind.TRANSITION]
    headline_cues = [c for c in cues if c.kind is CueKind.HEADLINE]
    row_cues = [c for c in cues if c.kind is CueKind.NUMBER_ROW]
    annotation_cues = [c for c in cues if c.kind is CueKind.ANNOTATION]
    zoom_cues = [c for c in cues if c.kind is CueKind.ZOOM]
    meme_cues = [c for c in cues if c.kind is CueKind.MEME]
    cutaway_cues = [c for c in cues if c.kind is CueKind.CUTAWAY]
    doodle_cues = [c for c in cues if c.kind is CueKind.DOODLE]
    scribble_cues = [c for c in cues if c.kind is CueKind.SCRIBBLE]
    alert_cues = [c for c in cues if c.kind is CueKind.ALERT]
    evidence_cues = [c for c in cues
                     if c.payload.get("class") in ("data", "punct")]

    layers: list[OverlayLayer] = []
    unresolved: list[str] = []
    # Every kit key this render actually put on screen. Written to the variant
    # ledger at the end, which is what makes "never used across recent
    # renders" a real measurement rather than a guess.
    used_keys: set[str] = set()

    # The stage is exclusive: a beat ENDS when the next one claims the frame.
    # Everything used to be placed with t_end=duration, so a sixty-second short
    # accumulated every card it had ever shown and finished with all of them on
    # screen at once.
    # When a data tag beat takes the stage it REPLACES what was there, so the
    # marks belonging to the old beat have to go with it. A scribble anchored
    # to a numbers row otherwise carries on being drawn over the card that
    # replaced the sheet, which is what it did.
    stage_claims = sorted(
        (float(c.t), float(c.t) + float(c.payload.get("hold", 0.0)))
        for c in cues
        if c.payload.get("class") == "data")

    def clip_to_stage(t0: float, default: float) -> tuple[float, float]:
        """A mark's window, with any stage claim taken out of it.

        Two ways a mark and a claim collide, and both were visible in a real
        render: the mark is up when a card lands (so it draws over the card),
        and the mark fires while a card is already up (so it appears on
        something it has nothing to do with). The first shortens it; the
        second defers it until the sheet is back.
        """
        for a, b in stage_claims:
            if a <= t0 < b:
                t0 = b
        nxt = next((a for a, _ in stage_claims if a > t0 + 0.05), None)
        return t0, (min(default, nxt) if nxt is not None else default)

    gut_t = float(numbers.t)
    trap_cue = next((c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP), None)
    trap_t = float(trap_cue.t) if trap_cue is not None else None
    payoff_t = float(conclusion.t)
    stage_open_end = float(host_open.payload.get("until", 0.0))
    close_t = float(host_close.t)

    opener = sample_hook_opener(script.content_sha(), settings)

    # -------------------------------------------- the acts, as three plates
    # One flat backdrop held dead still for seventy-five seconds is what made
    # the whole thing read as a slide deck. Three plates instead, at zero
    # cost: the desk set shipped four scenes and nothing touched them.
    #
    # These go on FIRST, at the bottom of the z-order, so everything else
    # composites over them exactly as it did over the bare backdrop.
    from PIL import Image

    # ------------------------------------------------- how big it all is
    # The number this whole layout exists to move. Every visual beat records
    # the fraction of the frame it actually occupies, so "the frame reads
    # empty" stops being an opinion: a 1:1 drawing contain-fitted into a
    # 1000x760 landscape box covers 28% of a 1080x1920 frame, and fitted to
    # the frame's width it covers 56%. Both are measurable and neither needed
    # anybody to watch the video.
    beat_coverage: list[dict] = []

    def note_beat(name: str, w: int, h: int, *, is_data: bool,
                  plate_of: tuple[int, int] | None = None) -> None:
        """Record one beat's size.

        `w, h` is the ARTWORK — what the brief asks for and the only number
        that cannot be inflated by the layout. `plate_of` is the drawing's own
        size when the beat has been composed onto a full-frame plate, so a
        card that owns the frame does not get to report itself as 100% of the
        frame when its typesetting still covers a third of it.
        """
        if w <= 0 or h <= 0:
            return
        art_w, art_h = plate_of if plate_of else (w, h)
        entry = {
            "name": name, "w": int(art_w), "h": int(art_h),
            "class": "data" if is_data else "punct",
            "frac": round(min(art_w * art_h / float(W * H), 1.0), 4),
        }
        if plate_of:
            entry["plated"] = True
            entry["beat_frac"] = round(min(w * h / float(W * H), 1.0), 4)
        if art_w >= W * 0.99 and art_h < H * 0.99:
            # As wide as the frame and no taller than its own aspect allows.
            # Nothing in the layout can grow this beat: a 16:9 asset on a 9:16
            # frame is 1080x607 — 32% — and the only lever left is redrawing
            # it. Marked so the median says WHICH assets are the constraint
            # rather than just that the number is short.
            entry["capped"] = "aspect"
            entry["source_aspect"] = round(art_w / max(art_h, 1), 3)
        beat_coverage.append(entry)

    def act_plate(key: str, name: str, t0: float, t1: float, *,
                  screen=None, y_frac: float = 0.36) -> None:
        asset = kit.get(key)
        if asset is None or t1 - t0 < 0.4:
            return
        used_keys.add(asset.key)
        dest = rdir / f"{name}.png"
        plate(asset, W, H, settings, screen=screen, y_frac=y_frac).convert(
            "RGBA").save(dest)
        layers.append(OverlayLayer(path=dest, x=0, y=0, t_start=t0, t_end=t1,
                                   name=name))

    def rotate_desk(t0: float, t1: float, name: str, *, screen=None,
                    y_frac: float = 0.36) -> None:
        """The room, changing angle across a long stretch.

        The gut check is the longest section of the short and it played on
        blank `room-tall` from start to finish, because only the open, the
        chart and the payoff had a desk plate. The set ships four scenes.
        """
        span = t1 - t0
        if span < 0.4:
            return
        n = max(int(span // DESK_ROTATE_S), 1)
        step = span / n
        # Seeded off the script so two shorts cut on the same day do not open
        # the same section on the same angle, deterministic within one.
        offset = int(hashlib.sha256(
            f"desk|{script.content_sha()}".encode()).hexdigest()[:8], 16)
        for i in range(n):
            key = DESK_SET[(offset + i) % len(DESK_SET)]
            act_plate(key, f"{name}_{i}", t0 + i * step,
                      t1 if i == n - 1 else t0 + (i + 1) * step,
                      screen=screen, y_frac=y_frac)

    act_plate(DESK_OPEN_KEY, "act_open", 0.0, stage_open_end)

    # ------------------------------------------- the branded chart (hero)
    # ON THE MONITOR, not floating on a wall. The desk scene declares a
    # `screen` box and nothing had ever put anything in it, so the chart sat
    # two hundred pixels from a drawing of the screen it belongs on.
    render_chart = (render_marker_price_chart
                    if script.chart_style is ChartStyle.MARKER else render_price_chart)
    desk = kit.get(DESK_CHART_KEY)
    screen_slot = desk.slot("screen") if desk else None
    if screen_slot is not None:
        # Drawn at the monitor's own aspect so it fills the glass rather than
        # being cover-cropped into it.
        chart_px = (px(880), max(int(px(880) * screen_slot.h / screen_slot.w), 1))
    else:
        chart_px = (px(1000), px(STAGE_H))
    chart_path, chart_meta = render_chart(
        prices, rdir / "chart.png", settings,
        size=chart_px, move_text=script.move_summary,
    )
    chart_img = Image.open(chart_path).convert("RGBA")

    # Where the chart ended up ON SCREEN, and how big it is relative to the
    # image the chart metadata is measured against. Marks that point at the
    # chart are placed through this, so moving the chart moves the marks.
    chart_scale = 1.0
    if desk is not None:
        used_keys.add(desk.key)
        desk_path = rdir / "desk_chart.png"
        slot_rects: dict[str, tuple[int, int, int, int]] = {}
        plate(desk, W, H, settings, screen=("screen", chart_img),
              y_frac=0.34, rects=slot_rects).convert("RGBA").save(desk_path)
        sx0, sy0, sw0, sh0 = slot_rects.get("screen", (0, 0, W, H))
        chart_pos = (sx0, sy0)
        # The chart is cover-cropped into the glass, so it is scaled by
        # whichever axis had to fill and re-centred on the other.
        cover = max(sw0 / max(chart_img.width, 1), sh0 / max(chart_img.height, 1))
        chart_scale = cover
        chart_pos = (int(sx0 - (chart_img.width * cover - sw0) / 2),
                     int(sy0 - (chart_img.height * cover - sh0) / 2))
        layers.append(OverlayLayer(
            path=desk_path, x=0, y=0,
            t_start=stage_open_end, t_end=gut_t, name="chart",
        ))
    else:
        chart_pos = (px(40), px(STAGE_Y))
        chart_draw = frames_to_alpha_clip(
            draw_on_frames(chart_img, fps=fps, seconds=0.9),
            fps, rdir / "chart_on.mov")
        layers.append(OverlayLayer(
            path=chart_draw, x=chart_pos[0], y=chart_pos[1],
            t_start=stage_open_end, t_end=gut_t, is_video=True, hold=True,
            name="chart",
        ))

    # The room through the middle — the gut check and the trap, which is most
    # of the runtime and had no backdrop beyond the flat plate. This goes in
    # HERE, with the other act plates, because z-order is list order: called
    # at the end it composited over the numbers sheet and the sheet vanished.
    rotate_desk(gut_t, payoff_t, "act_mid", y_frac=0.34)

    # ------------------------------------------------------------ hook card
    # The mute-safe line, ABOVE the stage — it reads over the host open and
    # stays through the WHY beat. Vertical video reads text-top,
    # action-centre, captions-bottom; this used to sit in the ledger band
    # under the artwork, so the top of the frame was empty and the bottom
    # third carried three competing blocks of type.
    hook_layout = _layout(HOOK_LAYOUTS, hook.payload.get("variant"))
    hook_img = text_panel(settings, hook.payload["text"], width=px(hook_layout["width"]),
                          font_name=SHANTELL, font_size=px(hook_layout["size"]),
                          accent=hook_layout["accent"])
    hook_clip = frames_to_alpha_clip(
        slide_in_frames(hook_img, fps=fps, seconds=0.4, direction="down"),
        fps, rdir / "hook.mov")
    layers.append(OverlayLayer(
        path=hook_clip, x=int((W - hook_img.width) / 2), y=px(hook_layout["y"]),
        t_start=0.0, t_end=float(hook.payload["until"]), is_video=True, hold=True,
        name="hook",
    ))

    # ------------------------------------- headlines overlaid ON the chart
    # Stacked below the desk when the chart is on the monitor — they are what
    # the shot is about, so they read under it rather than on top of the glass.
    #
    # They also share that band with the two-shot host inset, and a centred
    # 880-wide card ran straight under him: the second headline's text was
    # sliced off mid-word by his panel. The cards take the column to the LEFT
    # of the inset instead, which is what makes it a two-shot rather than two
    # things in one place.
    slots = chart_meta["headline_slots"]
    headline_w = W - px(INSET_W + INSET_MARGIN + INSET_GAP) - px(40)
    for c in headline_cues:
        i = int(c.payload["index"])
        meaning = script.headlines[i].meaning if i < len(script.headlines) else ""
        card = headline_card(
            settings, c.payload["text"], meaning=meaning,
            width=headline_w if desk is not None else px(880),
            font_size=px(30) if desk is not None else px(32))
        card_clip = frames_to_alpha_clip(
            slide_in_frames(card, fps=fps, seconds=0.35, direction="left"),
            fps, rdir / f"headline_{i}.mov")
        if desk is not None:
            hx = px(40)
            hy = px(1030) + i * (card.height + px(18))
        else:
            sx, sy = slots[min(i, len(slots) - 1)]
            hx, hy = chart_pos[0] + int(sx), chart_pos[1] + int(sy)
        layers.append(OverlayLayer(
            path=card_clip, x=hx, y=min(hy, H - card.height - px(200)),
            t_start=c.t, t_end=float(c.payload["until"]),
            is_video=True, hold=True, name=f"headline_{i}",
        ))

    # -------------------------------------------------- the numbers sheet
    # Drawn as wide as the stage band allows, then narrowed only if the rows
    # would run past it. A six-row sheet at full width is taller than the
    # band; shrinking the width shrinks the rows with it, because every metric
    # scales off the width.
    sheet_layout = _layout(NUMBERS_LAYOUTS, numbers.payload.get("variant"))
    sheet_top = px(sheet_layout["y"])
    band_h = max(px(STAGE_Y + STAGE_H) - sheet_top, px(200))
    sheet_w = px(sheet_layout["width"])
    while sheet_w > px(560):
        sheet_img, layout = numbers_sheet_base(
            settings, len(script.numbers), script.years, width=sheet_w)
        if sheet_img.height <= band_h:
            break
        sheet_w = int(sheet_w * 0.92)
    else:
        sheet_img, layout = numbers_sheet_base(
            settings, len(script.numbers), script.years, width=sheet_w)
    sheet_path = rdir / "sheet.png"
    sheet_img.save(sheet_path)
    sheet_pos = (int((W - sheet_img.width) / 2), sheet_top)
    # The sheet owns the stage until the value-trap card (or the payoff) takes
    # it. Leaving it up to the end is how the payoff card ended up behind it.
    sheet_end = trap_t if trap_t is not None else payoff_t
    layers.append(OverlayLayer(
        path=sheet_path, x=sheet_pos[0], y=sheet_pos[1],
        t_start=numbers.t, t_end=sheet_end, fade_in=0.2, name="numbers_sheet",
    ))
    note_beat("numbers_sheet", sheet_img.width, sheet_img.height, is_data=True)

    row_geo: dict[int, tuple[int, int]] = {}
    for c in row_cues:
        i = int(c.payload["index"])
        clip = frames_to_alpha_clip(
            number_row_frames(settings, c.payload["label"], c.payload["values"],
                              layout, fps=fps,
                              type_seconds=float(c.payload["type_seconds"])),
            fps, rdir / f"row_{i}.mov",
        )
        ry = sheet_pos[1] + layout["rows_y0"] + i * layout["row_h"]
        row_geo[i] = (sheet_pos[0], ry)
        layers.append(OverlayLayer(
            path=clip, x=sheet_pos[0], y=ry,
            t_start=c.t, t_end=sheet_end, is_video=True, hold=True,
            name=f"number_row_{i}",
        ))

    # ------------------------- hand-drawn scribbles (chart & numbers rows)
    for k, c in enumerate(annotation_cues):
        target = c.payload["target"]
        if target == "chart":
            lx, ly = chart_meta["last_point"]
            # `last_point` is in the chart IMAGE's pixels; on the desk the
            # chart is scaled into the monitor, so the mark scales with it.
            sw = max(int(px(240) * min(chart_scale, 1.0)), px(90))
            sh = max(int(px(190) * min(chart_scale, 1.0)), px(70))
            x = chart_pos[0] + int(lx * chart_scale) - sw // 2
            y = chart_pos[1] + int(ly * chart_scale) - sh // 2
            # a mark on the chart leaves with the chart; a mark on a row
            # leaves with the sheet. Neither outlives what it points at.
            t_start, t_end = clip_to_stage(c.t, gut_t)
        else:
            i = int(c.payload["row_index"] or 0)
            rx, ry = row_geo.get(i, (sheet_pos[0], sheet_pos[1]))
            sw, sh = px(1000), layout["row_h"]
            x, y = rx, ry
            t_start, t_end = clip_to_stage(c.t, sheet_end)
        x = min(max(x, px(6)), W - sw - px(6))
        y = min(max(y, px(6)), H - sh - px(6))
        clip = frames_to_alpha_clip(
            scribble_frames(sw, sh, style="circle", fps=fps,
                            seed=f"{script.ticker}|{k}"),
            fps, rdir / f"scribble_{k}.mov",
        )
        layers.append(OverlayLayer(
            path=clip, x=x, y=y, t_start=t_start, t_end=t_end,
            is_video=True, hold=True, name=f"scribble_{k}_{target}",
        ))
        note = (c.payload.get("note") or "").strip()
        if note:
            note_img = simple_text(settings, note, font_size=px(32),
                                   fill=(*RED, 255), stroke_width=2)
            note_path = rdir / f"note_{k}.png"
            note_img.save(note_path)
            if target == "chart":
                nx = min(x + sw // 2 - note_img.width // 2,
                         W - note_img.width - px(16))
                ny = min(y + sh + px(4), H - note_img.height - px(10))
            else:
                nx = W - note_img.width - px(56)
                ny = y - note_img.height + px(10)
            layers.append(OverlayLayer(
                path=note_path, x=max(nx, px(10)), y=max(ny, px(10)),
                t_start=t_start, t_end=t_end, fade_in=0.15, name=f"note_{k}",
            ))

    # ------------------------------- count-up on the key number(s)
    # The figure rolls to the value as it is spoken, then holds. This is the
    # zoom-punch's replacement: a number that arrives by counting is read;
    # a number that arrives by scaling is a transition.
    for k, c in enumerate(zoom_cues):
        i = int(c.payload["row_index"])
        if i >= len(script.numbers):
            continue
        value = script.numbers[i].values[-1]
        rx, ry = row_geo.get(i, sheet_pos)
        cw, ch = px(340), layout["row_h"]
        frames = count_up_frames(settings, value, width=cw, height=ch,
                                 fps=fps, seconds=0.7, align="center")
        clip = frames_to_alpha_clip(frames, fps, rdir / f"countup_{k}.mov")
        cu_start, cu_end = clip_to_stage(c.t, min(c.t + 1.4, sheet_end))
        layers.append(OverlayLayer(
            path=clip, x=int(rx + px(1000) - layout["bars_w"] - cw),
            y=ry, t_start=cu_start, t_end=cu_end,
            is_video=True, hold=True, name=f"countup_{k}",
        ))

    # ------------------------- the numbers batch, reached for automatically
    # Twenty-three drawings whose whole job is making a figure land, and they
    # only ever appeared if the writer named one — so most videos used none.
    # A key-number beat the script did not tag picks one off the number
    # itself: up gets a drawing about going up, a deepening loss gets the
    # hole. This is what turns the core batch from occasional into
    # every-video.
    tagged_props = {str(c.payload.get("value", "")).lower()
                    for c in evidence_cues}

    # ONE of them goes full-bleed. Eleven of the kit's drawings are 1080x1920
    # compositions — the only assets built to BE this frame — and
    # `is_full_frame` has always routed them correctly. They just never fired,
    # because they only appeared when a writer named one by key, so the assets
    # drawn to fill the frame were the assets a short never used. One per
    # video: a short that cuts to full-bleed six times is emphasising nothing.
    vertical_done = False
    for k, c in enumerate(zoom_cues):
        i = int(c.payload["row_index"])
        if i >= len(script.numbers):
            continue
        row = script.numbers[i]

        if not vertical_done:
            picked = vertical_beat_for_row(
                kit, row.label, row.values, seed=script.content_sha(),
                ledger=beat_ledger, exclude=tagged_props)
            if picked is not None:
                vkey, vvalues = picked
                scene = kit.get(vkey)
                if scene is not None:
                    vspan = max(playback_seconds(scene), 2.2)
                    vstart, _ = clip_to_stage(c.t, duration)
                    vend = min(vstart + vspan, sheet_end)
                    if vend - vstart >= 1.2:
                        vertical_done = True
                        used_keys.add(scene.key)
                        vimg = cover_on_paper(
                            render_still(scene, vvalues, settings), W, H)
                        vdest = rdir / f"verticalbeat_{k}.png"
                        vimg.convert("RGBA").save(vdest)
                        layers.append(OverlayLayer(
                            path=vdest, x=0, y=0, t_start=vstart, t_end=vend,
                            fade_in=0.12,
                            name=f"vertical_{vkey.rsplit('/', 1)[-1][:18]}",
                        ))
                        note_beat(f"vertical_{scene.name}", vimg.width,
                                  vimg.height, is_data=True)
                        continue    # the frame is taken; no corner drawing
        # The writer's own props are excluded from the bank BEFORE the draw,
        # not filtered out after it: picking then discarding lost the beat
        # entirely whenever the dice landed on a drawing already named in the
        # script, which is how a render reached for `crushed-flat` twice and
        # shipped the row with nothing.
        chosen = beat_for_row(kit, row.label, row.values,
                              seed=script.content_sha(), ledger=beat_ledger,
                              exclude=tagged_props)
        if chosen is None:
            continue
        key, slot_values = chosen
        asset = kit.get(key)
        if asset is None:
            continue
        span = max(playback_seconds(asset), 1.6)
        start, _ = clip_to_stage(c.t, duration)
        end = min(start + span, sheet_end)
        if end - start < 1.0:
            continue
        # Claimed only once it is going on screen. Counting it above meant the
        # manifest listed assets the render had dropped, and the manifest is
        # the evidence the rebuild landed.
        used_keys.add(asset.key)
        img = fit_into(render_still(asset, slot_values, settings),
                       px(560), px(560))
        beat_clip = frames_to_alpha_clip(
            slide_in_frames(img, fps=fps, seconds=0.3, direction="up"),
            fps, rdir / f"numberbeat_{k}.mov")
        layers.append(OverlayLayer(
            path=beat_clip, x=W - img.width - px(40),
            y=px(STAGE_Y + 300), t_start=start, t_end=end,
            is_video=True, hold=True,
            name=f"numberbeat_{k}_{key.rsplit('/', 1)[-1][:18]}",
        ))
        note_beat(f"numberbeat_{asset.name}", img.width, img.height,
                  is_data=False)

    # ---------------------------------------------- the tag grammar beats
    # Everything the script asked for by name. A card tag gets its named
    # artwork or the blank layout filled with the script's own text; a shorts
    # asset plays its strip; a filing, article or screengrab is a real image.
    #
    # The punch counter runs across the whole sequence and advances only on
    # beats that could punch, so the emphasis lands every third DRAWING rather
    # than every third cue.
    punch_cycle = [0]
    for k, c in enumerate(evidence_cues):
        tag = TagType(c.payload["tag"]) if c.payload.get("tag") else None
        value = str(c.payload.get("value", ""))
        hold = float(c.payload.get("hold", 1.6))
        is_data = c.payload.get("class") == "data"
        name = f"tag_{k}_{c.kind.value}"
        placed = _place_evidence(
            kit=kit, tag=tag, value=value, cue=c, script=script,
            settings=settings, content=content, workspace=workspace,
            rdir=rdir, layers=layers, W=W, H=H, px=px, fps=fps,
            duration=duration, hold=hold, is_data=is_data, name=name,
            used_keys=used_keys, punch_cycle=punch_cycle,
            note=note_beat,
        )
        if not placed:
            unresolved.append(f"[{tag.value if tag else c.kind.value}: {value}]")

    # ----------------------------------------------- meme freeze / cutaway
    for k, c in enumerate(meme_cues):
        if c.payload.get("tag"):
            continue  # already placed by the tag grammar above
        meme = content.resolve_meme(c.payload["key"])
        from PIL import Image, ImageOps

        m = Image.open(meme.path).convert("RGB")
        m.thumbnail((px(880), px(700)), Image.LANCZOS)
        framed = ImageOps.expand(m, border=px(14), fill=(250, 249, 246))
        meme_path = rdir / f"meme_{k}.png"
        framed.save(meme_path)
        hold = float(c.payload["duration"])
        layers.append(OverlayLayer(
            path=meme_path, x=int((W - framed.width) / 2),
            y=int(H * 0.34), t_start=c.t, t_end=min(c.t + hold, duration),
            name=f"meme_{k}",
        ))

    for k, c in enumerate(cutaway_cues):
        clip = content.resolve_clip(c.payload["key"], portrait=True)
        hold = float(c.payload["duration"])
        layers.append(OverlayLayer(
            path=clip.path, x=0, y=0,
            t_start=c.t, t_end=min(c.t + hold, duration),
            is_video=True, hold=True, name=f"cutaway_{k}",
        ))

    # ------------------------------ inline hand-drawn doodles (TOP layer)
    doodle_slots = [(px(560), px(560)), (px(120), px(600)), (px(540), px(1180)),
                    (px(120), px(1180))]
    for k, c in enumerate(doodle_cues):
        visual = content.resolve_doodle(c.payload["value"])
        if visual is None:
            log.warning("doodle %r not resolved — skipped", c.payload["value"])
            unresolved.append(f"[DOODLE: {c.payload['value']}]")
            continue
        hold = float(c.payload.get("hold", 1.6))
        clip, (cw, ch) = doodle_clip(
            visual.path, rdir / f"doodle_{k}.mov",
            display_w=px(380), duration_s=hold + 0.2, fps=fps,
            seed=f"{script.ticker}|doodle|{k}",
        )
        sx, sy = doodle_slots[k % len(doodle_slots)]
        # An inline mark rides on top of the frame — but not on top of a card
        # it has nothing to do with. Deferred past an active data beat, the
        # same way a numbers-row annotation is.
        d_start, _ = clip_to_stage(c.t, duration)
        layers.append(OverlayLayer(
            path=clip, x=min(sx, W - cw), y=min(sy, H - ch),
            t_start=d_start, t_end=min(d_start + hold, duration),
            is_video=True, name=f"doodle_{k}_{visual.key[:16]}",
        ))

    # ---------------- inline scribbles (drawn mark + target callout, TOP)
    for k, c in enumerate(scribble_cues):
        parsed = parse_scribble_payload(c.payload["value"])
        if parsed is None:
            continue
        style, target = parsed
        hold = float(c.payload.get("hold", 1.6))
        sw, sh = px(520), px(360)
        frames = scribble_callout_frames(
            settings, sw, sh, style=style.value, target=target,
            fps=fps, hold_seconds=hold, seed=f"{script.ticker}|scr|{k}",
        )
        clip = frames_to_alpha_clip(frames, fps, rdir / f"scribble_inline_{k}.mov")
        # A callout naming a number belongs on the frame that shows it, so it
        # waits out a card that has claimed the stage rather than drawing
        # "Net income" across an unrelated term definition.
        s_start, _ = clip_to_stage(c.t, duration)
        layers.append(OverlayLayer(
            path=clip, x=int((W - sw) / 2), y=px(STAGE_Y + 300),
            t_start=s_start, t_end=min(s_start + hold + 0.5, duration),
            is_video=True, hold=True, name=f"scribble_inline_{k}",
        ))

    # --------------------------------------- [ALERT] lower-third overlays
    for k, c in enumerate(alert_cues):
        asset = kit.resolve_asset(KIT_TAG_FAMILIES[TagType.ALERT],
                                  str(c.payload.get("value", "")))
        hold = float(c.payload.get("hold", 2.4))
        if asset is None:
            unresolved.append(f"[ALERT: {c.payload.get('value')}]")
            continue
        img = fit_into(render_still(asset, None, settings), px(940), px(300))
        clip = frames_to_alpha_clip(
            slide_in_frames(img, fps=fps, seconds=0.3, direction="right"),
            fps, rdir / f"alert_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=int((W - img.width) / 2), y=int(H * 0.68),
            t_start=c.t, t_end=min(c.t + hold, duration),
            is_video=True, hold=True, name=f"alert_{k}",
        ))

    # ------------------------------------------- beat-transition stingers
    # A kit transition when one exists, the flash when none does.
    #
    # Every cut fires the same white flash today, because the 6-frame ink
    # strips the design docs specify were never exported — there is no
    # `stings/` family in the registry. The picker is wired now so the strips
    # drop in as data when they are commissioned; until then this is honestly
    # a fallback rather than the design.
    flash = frames_to_alpha_clip(
        flash_frames(W, H, fps=fps), fps, rdir / "flash.mov",
    )
    for ti, c in enumerate(t for t in transitions if t.t > 0.05):
        strip = transition_asset(kit, script.content_sha(), ti, frame=(W, H))
        name = f"flash_{c.payload['name']}"
        if strip is None:
            layers.append(OverlayLayer(
                path=flash, x=0, y=0, t_start=c.t,
                t_end=min(c.t + 0.2, duration), is_video=True, name=name))
            continue
        used_keys.add(strip.key)
        span = max(playback_seconds(strip), 0.25)
        clip, (cw, ch) = render_clip(
            strip, rdir / f"transition_{ti}.mov", duration_s=span, fps=fps,
            settings=settings,
            transform=transition_transform(strip, W, H, settings))
        layers.append(OverlayLayer(
            path=clip, x=0, y=0, t_start=c.t,
            t_end=min(c.t + span, duration), is_video=True,
            name=f"{name}_{strip.name[:16]}"))

    # ------------------------------- cheap or trap: the value-trap beat
    for c in (c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP):
        trap_img = text_panel(settings, c.payload["text"], width=px(980),
                              font_name=SHANTELL, font_size=px(46), accent=RED,
                              bg=(250, 249, 246, 242))
        trap_clip = frames_to_alpha_clip(
            slide_in_frames(trap_img, fps=fps, seconds=0.4, direction="up"),
            fps, rdir / "cheap_or_trap.mov")
        layers.append(OverlayLayer(
            path=trap_clip, x=int((W - trap_img.width) / 2), y=px(STAGE_Y + 120),
            t_start=c.t, t_end=min(float(c.payload["until"]), payoff_t),
            is_video=True, hold=True, name="cheap_or_trap",
        ))

    # ------------------------------------------------- the payoff
    # The card slams onto the stage; the deadpan line lands in the ledger under
    # it and stays to the end. Not a verdict stamp — the card is the shape the
    # channel closes on and the words are what it actually said.
    card_key = payoff_card_key(conclusion.payload["text"])
    card_asset = kit.get(card_key)
    if card_asset is not None:
        # Full width. At 940 design px this closed the video on a card
        # covering 18% of the frame — the smallest beat in the short was the
        # one it ends on.
        card_img = fit_into(render_still(card_asset, None, settings),
                            min(px(1080), W), px(560))
        card_clip = frames_to_alpha_clip(
            stamp_slam_frames(card_img, fps=fps, seconds=0.45),
            fps, rdir / "payoff_card.mov")
        # The close can start before the payoff on a script whose conclusion
        # lands late: the timeline gives the host bookend a floor of three
        # seconds regardless. Clamp rather than emit a backwards window.
        card_end = max(min(payoff_t + 2.4, close_t), payoff_t + 0.6)
        layers.append(OverlayLayer(
            path=card_clip, x=int((W - card_img.width) / 2), y=px(STAGE_Y + 140),
            t_start=payoff_t, t_end=min(card_end, duration),
            is_video=True, hold=True, name="payoff_card",
        ))
        note_beat("payoff_card", card_img.width, card_img.height, is_data=True)
    else:
        unresolved.append(card_key)

    act_plate(DESK_PAYOFF_KEY, "act_payoff", payoff_t, duration, y_frac=0.30)

    payoff_layout = _layout(PAYOFF_LAYOUTS, conclusion.payload.get("variant"))
    conc_img = text_panel(settings, conclusion.payload["text"], width=px(960),
                          font_name=SHANTELL, font_size=px(payoff_layout["size"]),
                          accent=payoff_layout["accent"], bg=(250, 249, 246, 246))
    conc_path = rdir / "conclusion.png"
    conc_img.save(conc_path)
    # The signature close is the channel's tail card and owns the frame for
    # its last beat — the payoff line and the host both end when it lands,
    # rather than showing through it three deep.
    e_close_t = max(duration - max(playback_seconds(kit.get(CLOSE_KEY)), 1.6), 0.0)
    layers.append(OverlayLayer(
        path=conc_path, x=int((W - conc_img.width) / 2), y=px(payoff_layout["y"]),
        t_start=payoff_t, t_end=max(e_close_t, payoff_t + 0.6),
        fade_in=0.25, name="conclusion",
    ))

    # ------------------------------------------------------- the host rig
    # Dennis goes on LAST so he is on top of the stage, not under it. He was
    # the first thing composited before, which put the chart, the sheet and
    # every card over his face — a host you cannot see is a host you do not
    # have.
    #
    # Bookends are full-width on the stage. A mid-video return is the two-shot:
    # a smaller inset beside the evidence, which stays up, so the cut never
    # leaves him and never hides what he is talking about.
    host_shot_i = 0

    def add_host(cue, role: str, name: str, *, inset: bool = False) -> bool:
        nonlocal host_shot_i
        t0, t1 = float(cue.t), float(cue.payload.get("until", cue.t))
        t1 = min(t1, duration)
        if t1 <= t0:
            return False
        width = px(INSET_W) if inset else W
        built = build_host_clip(
            tts.words, t0, t1, rdir / f"host_{name}.mov",
            kit=kit, settings=settings, display_w=width, fps=fps,
            role=role, shot_index=host_shot_i, strip_furniture=True,
        )
        host_shot_i += 1
        if built is None:
            return False
        clip, (hw, hh) = built
        shot = pick_shot(kit, role, host_shot_i - 1)
        if shot is not None:
            used_keys.update({shot.closed.key, shot.open_.key})
        if inset:
            x, y = W - hw - px(INSET_MARGIN), px(INSET_Y)
        else:
            x, y = int((W - hw) / 2), px(HOST_Y)
        layers.append(OverlayLayer(
            path=clip, x=x, y=min(y, H - hh), t_start=t0, t_end=t1,
            is_video=True, hold=True, name=f"host_{name}",
        ))
        return True

    if not add_host(host_open, "open", "open"):
        raise KitError(
            "the SHORT has no host: no usable talk pair in the kit's cold-open "
            "bank. Dennis opens and closes every short on camera — a render "
            "without him is the bug, not a degraded mode. Run `/kit doctor`.")
    host_close.payload["until"] = min(
        float(host_close.payload.get("until", duration)), e_close_t)
    add_host(host_close, "close", "close")
    for i, c in enumerate(host_beats):
        add_host(c, "panel", f"beat{i}", inset=True)

    # ------------------------------------------- the signature open/close
    # Full-frame, over everything including the host: they are the channel's
    # top and tail, not a layer in the composition.
    open_asset = kit.get(OPEN_KEY)
    open_hold = max(playback_seconds(open_asset), 1.4)
    open_clip, _ = render_clip(
        open_asset, rdir / "e_open.mov", duration_s=open_hold, fps=fps,
        settings=settings, display_w=W,
        values={"title": f"${script.ticker}",
                "strapline": settings.brand_tagline.lower()},
    )
    layers.append(OverlayLayer(
        path=open_clip, x=0, y=0, t_start=0.0,
        t_end=min(open_hold, duration), is_video=True, name="e_open",
    ))

    close_asset = kit.get(CLOSE_KEY)
    close_hold = duration - e_close_t
    close_clip, _ = render_clip(
        close_asset, rdir / "e_close.mov", duration_s=close_hold, fps=fps,
        settings=settings, display_w=W,
        values={"line": settings.brand_tagline.lower(),
                "handle": settings.brand_handle},
    )
    layers.append(OverlayLayer(
        path=close_clip, x=0, y=0, t_start=e_close_t, t_end=duration,
        is_video=True, hold=True, name="e_close",
    ))

    # ---------------------------------------------------------- furniture
    # Last, so it survives a full-bleed beat. The ticker pill and the bug are
    # the only two things besides the captions that are on screen for the whole
    # video; composited first, as they were, a 9:16 scene erased them.
    pill = ticker_pill(settings, script.ticker, font_size=px(38))
    pill_path = rdir / "ticker_pill.png"
    pill.save(pill_path)
    layers.append(OverlayLayer(
        path=pill_path, x=px(40), y=px(56), t_start=0.0, t_end=duration,
        name="ticker_pill",
    ))
    bug = simple_text(settings, opener, font_size=px(28),
                      fill=(143, 140, 131, 240), stroke_width=0)
    bug_path = rdir / "bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=W - bug.width - px(40), y=px(70),
        t_start=0.0, t_end=duration, name="brand_bug",
    ))

    # -------------------------------------------------------- disclaimer
    disc_img = simple_text(settings, settings.disclaimer_text, font_size=px(28),
                           fill=(143, 140, 131, 235), stroke_width=0)
    disc_path = rdir / "disclaimer.png"
    disc_img.save(disc_path)
    layers.append(OverlayLayer(
        path=disc_path, x=int((W - disc_img.width) / 2), y=H - px(66),
        t_start=0.0, t_end=duration, name="disclaimer",
    ))

    # ---------------------------------------------------------- captions
    # Dark ink on a paper chip, phrase by phrase. The red karaoke fill was
    # colouring text the same red the kit reserves for a down-move, on lines
    # that had been split wherever the page happened to fill up.
    ass_path = rdir / "captions.ass"
    ass_path.write_text(build_phrase_ass(
        tts.words, play_res=(W, H), font_size=px(58),
        margin_v=px(CAPTION_MARGIN_V), duration=duration,
    ), encoding="utf-8")

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, start_s=0.0, gain_db=0.0, voice=True)]
    music = settings.assets_dir / "music" / "dennis_bed.m4a"
    if music.exists():
        audio.append(AudioTrack(path=music, gain_db=settings.music_gain_db, loop=True))
    sfx_dir = settings.assets_dir / "sfx"
    whoosh = sfx_dir / "whoosh.wav"
    if whoosh.exists():
        for c in transitions:
            if c.t > 0.05:
                audio.append(AudioTrack(path=whoosh, start_s=c.t,
                                        gain_db=settings.sfx_gain_db))
    sting = sfx_dir / "sting.wav"
    if sting.exists():
        for c in headline_cues:
            audio.append(AudioTrack(path=sting, start_s=c.t,
                                    gain_db=settings.sfx_gain_db))
    pop_wav = sfx_dir / "pop.wav"
    if pop_wav.exists():
        for c in zoom_cues:
            audio.append(AudioTrack(path=pop_wav, start_s=c.t,
                                    gain_db=settings.sfx_gain_db + 2))
    boom = sfx_dir / "vine_boom.wav"
    if boom.exists():
        for c in meme_cues:
            audio.append(AudioTrack(path=boom, start_s=c.t,
                                    gain_db=settings.sfx_gain_db + 2))
    scratch = sfx_dir / "record_scratch.wav"
    if scratch.exists():
        for c in cutaway_cues:
            audio.append(AudioTrack(path=scratch, start_s=max(c.t - 0.15, 0.0),
                                    gain_db=settings.sfx_gain_db))

    # ------------------------------------------------------------ encode
    # The backdrop holds dead still. NOTHING in this pipeline pans or zooms:
    # 84 of the kit's assets carry their own motion, and drift on top of a
    # registered frame sequence makes the registration itself look broken.
    # A backwards or zero-length window is a filtergraph error, not a
    # no-op: ffmpeg rejects a negative tpad `stop_duration` and the whole
    # render dies. Beat boundaries are derived from the audio, so a short
    # script can legitimately produce one; drop it here rather than let one
    # degenerate layer cost the cut.
    degenerate = [l.name for l in layers if l.t_end <= l.t_start]
    if degenerate:
        log.warning("dropping %d zero-length layer(s): %s",
                    len(degenerate), ", ".join(degenerate))
        layers = [l for l in layers if l.t_end > l.t_start]

    base_filter = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1,format=yuv420p"
    )
    spec = CompositeSpec(
        base_input_args=[
            "-loop", "1", "-framerate", str(fps),
            "-t", f"{duration:.3f}", "-i", str(backdrop.path),
        ],
        base_filter=base_filter,
        layers=layers,
        audio=audio,
        ass_path=ass_path,
        fonts_dir=settings.fonts_dir,
        duration=duration,
        fps=fps,
        # Mock audio is a placeholder tone, not a programme: normalising it
        # is what made a render come out silent.
        normalise_audio=not (settings.mocking_tts or getattr(tts, "draft", False)),
    )
    out_path = workspace / out_name
    composite_video(spec, encode_profile(settings, "short"), settings.audio_bitrate,
                    out_path)

    rendered = ffprobe_duration(out_path)
    if abs(rendered - duration) > 0.5:
        raise RenderError(
            f"rendered duration {rendered:.2f}s deviates from the audio master "
            f"clock {duration:.2f}s"
        )

    used_keys.update({BACKDROP_KEY, OPEN_KEY, CLOSE_KEY})
    if card_asset is not None:
        used_keys.add(card_asset.key)
    # The doctor diffs the library against this. A render that reached forty
    # assets and one that reached six look identical without it.
    for key in sorted(used_keys):
        asset = kit.get(key)
        if asset is not None:
            beat_ledger.record(asset.family, asset.key)
    beat_ledger.save()

    if unresolved:
        log.warning("short: %d tag key(s) did not resolve: %s",
                    len(unresolved), ", ".join(unresolved))

    manifest_path = workspace / "render_short_manifest.json"
    manifest_path.write_text(json.dumps({
        "ticker": script.ticker,
        "duration": duration,
        "opener": opener,
        "theme": "light",
        "host": {"shots": host_shot_i, "bookends": True},
        "chart": {"source": prices.source, "degraded": prices.degraded,
                  "direction": chart_meta["direction"],
                  "style": script.chart_style.value},
        "cues": [c.model_dump() for c in cues],
        "pacing_warnings": pacing_warnings,
        "unresolved_keys": unresolved,
        # How much of the frame each beat actually takes, and the median of
        # the ones the viewer is meant to READ. This is the number the layout
        # exists to move and it is checkable without anybody's opinion: a 1:1
        # drawing contain-fitted into a landscape box was 28% of frame, and
        # the whole video read as cards floating in paper.
        "beat_coverage": beat_coverage,
        "median_data_coverage": _median_coverage(beat_coverage, "data"),
        "median_punct_coverage": _median_coverage(beat_coverage, "punct"),
        # What the layout cannot fix. A beat is aspect-capped when it is
        # already the frame's full width and its own aspect sets its height,
        # so the only lever left is redrawing the asset.
        "aspect_capped_beats": [
            {"name": b["name"], "frac": b["frac"],
             "source_aspect": b.get("source_aspect")}
            for b in beat_coverage if b.get("capped") == "aspect"
        ],
        "kit_assets_used": sorted(used_keys),
        "layer_names": sorted({l.name for l in layers}),
        "layers": [
            {"name": l.name, "t_start": l.t_start, "t_end": l.t_end, "x": l.x, "y": l.y}
            for l in layers
        ],
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2), encoding="utf-8")
    return out_path, manifest_path


def _place_evidence(*, kit: Kit, tag, value: str, cue, script: ShortScript,
                    settings: Settings, content: ContentManager, workspace: Path,
                    rdir: Path, layers: list[OverlayLayer], W: int, H: int,
                    px, fps: int, duration: float, hold: float, is_data: bool,
                    name: str, used_keys: set[str] | None = None,
                    punch_cycle: list[int] | None = None,
                    note=None) -> bool:
    """Composite one tag beat. Returns False when the key did not resolve.

    Data beats take the frame — fitted large and centred. Punctuation rides
    smaller and off to one side, over whatever is already up, which is what
    keeps a reaction from erasing the thing it is reacting to.
    """
    from PIL import Image

    from pipeline.company_data import prepare_screenshot
    from pipeline.filings import screenshot_article

    # A data beat TAKES the stage; punctuation is LAYERED over whatever is
    # already there, smaller and lower, so a reaction never erases the thing
    # it is reacting to.
    box = stage_box(W, H, px, is_data=is_data)
    y = px(STAGE_Y) if is_data else px(STAGE_Y + 380)
    t_end = min(cue.t + hold, duration)

    def place_still(img, *, register: str = STAGE, asset=None) -> bool:
        placed, x, top = _frame_for(img, register, box, y, W, H, px, asset,
                                    punct=not is_data)
        art = placed.size
        if register == STAGE and is_data and _is_typeset(asset):
            # A pure typography read OWNS the frame. The blank layouts are
            # 1920x1080, so on a 9:16 frame the card is 1080x607 whatever we
            # do — but a word and its definition hovering over a drawing of a
            # desk is two things competing, and stage exclusivity says a data
            # beat replaces the frame rather than floating on it. On paper, so
            # the card's own paper and the plate's are the same sheet.
            plated = Image.new("RGBA", (W, H), (242, 242, 239, 255))
            plated.alpha_composite(placed, (x, max(int((H - placed.height) / 2), 0)))
            placed, x, top = plated, 0, 0
        if note is not None:
            note(name, placed.width, placed.height, is_data=is_data,
                 plate_of=art if art != placed.size else None)
        frames = (stamp_slam_frames(placed, fps=fps, seconds=0.35) if is_data
                  else slide_in_frames(placed, fps=fps, seconds=0.3, direction="up"))
        if register == FULL_BLEED:
            # A full-frame scene is a CUT, not an arrival. Slamming a shot
            # that already fills the frame just shakes the whole video.
            frames = [placed]
        clip = frames_to_alpha_clip(frames, fps, rdir / f"{name}.mov")
        layers.append(OverlayLayer(
            path=clip, x=x, y=top,
            t_start=cue.t, t_end=t_end, is_video=True, hold=True, name=name))
        return True

    if tag in (TagType.TERM, TagType.BIGNUM, TagType.PROP):
        asset, is_blank = _kit_asset_for(kit, tag, value)
        if asset is None:
            return False
        if used_keys is not None:
            used_keys.add(asset.key)
        # THE SLOTS. Named artwork used to take a `None` here, so every one of
        # the 74 declared boxes rendered empty — `[PROP: crushed-flat]`
        # resolved, played its six frames, and showed Dennis being crushed
        # under a blank rectangle. The value is written on the tag now.
        if is_blank:
            values = _blank_values(tag, value, script,
                                   cue.payload.get("values"))
        else:
            values, slot_warnings = bind_slot_values(
                asset, cue.payload.get("values"))
            for w in slot_warnings:
                log.warning("slot: %s", w)

        register = _register_for(asset, is_data,
                                 punch_cycle if punch_cycle is not None
                                 else [0], (W, H))
        if asset.animated:
            # A one-shot must run its whole strip: a six-frame transformation
            # cut at three frames is a drawing of nothing having happened.
            span = max(hold, playback_seconds(asset))
            t_end2 = min(cue.t + span, duration)
            transform = _transform_for(register, asset, box, W, H, px)
            clip, (cw, ch) = render_clip(
                asset, rdir / f"{name}.mov", duration_s=t_end2 - cue.t, fps=fps,
                settings=settings, values=values, transform=transform)
            x, top = _origin_for(register, cw, ch, y, W, punct=not is_data)
            if note is not None:
                note(name, cw, ch, is_data=is_data)
            layers.append(OverlayLayer(
                path=clip, x=x, y=top, t_start=cue.t,
                t_end=t_end2, is_video=True, hold=True, name=name))
            return True
        return place_still(
            strip_baked_furniture(render_still(asset, values, settings), asset),
            register=register, asset=asset)

    if tag is TagType.SHOW_ARTICLE:
        shot = screenshot_article(value, rdir / f"{name}.png", settings)
        if shot is None:
            return False
        return place_still(Image.open(shot).convert("RGBA"))

    if tag is TagType.SHOW_FILING:
        src = workspace / value
        if not src.exists():
            return False
        prepared = prepare_screenshot(src, rdir / f"{name}.png", settings)
        return place_still(Image.open(prepared).convert("RGBA"))

    if tag is TagType.SCREENGRAB:
        try:
            visual = content.resolve_screengrab(value)
        except Exception:  # noqa: BLE001 — a missing capture is a tag miss
            return False
        if visual.is_video:
            layers.append(OverlayLayer(
                path=visual.path, x=0, y=0, t_start=cue.t, t_end=t_end,
                is_video=True, hold=True, name=name))
            return True
        return place_still(Image.open(visual.path).convert("RGBA"))

    if tag in (TagType.IMG, TagType.PRODUCT):
        try:
            visual = content.resolve_image(value, kind="img")
        except Exception:  # noqa: BLE001
            return False
        return place_still(Image.open(visual.path).convert("RGBA"))

    if tag is TagType.MEME:
        try:
            visual = content.resolve_meme(value)
        except Exception:  # noqa: BLE001
            return False
        return place_still(Image.open(visual.path).convert("RGBA"))

    if tag in (TagType.CLIP, TagType.BROLL):
        try:
            visual = content.resolve_clip(value, portrait=True)
        except Exception:  # noqa: BLE001
            return False
        layers.append(OverlayLayer(
            path=visual.path, x=0, y=0, t_start=cue.t, t_end=t_end,
            is_video=True, hold=True, name=name))
        return True

    return False


# --------------------------------------------------------------------------
# Framing: which register a beat gets, and where it lands.
# --------------------------------------------------------------------------
# Every beat used to land in the same box at the same size — one register for
# thirty-eight assets — which is why a well-populated cut still read as a
# slideshow. Three registers, chosen per beat and then HELD: the variety is in
# which shot, never in movement inside one.

# Every third eligible beat punches in. Often enough to break the rhythm, rare
# enough that it stays an emphasis rather than a tic.
PUNCH_EVERY = 3


def _register_for(asset, is_data: bool, punch_cycle: list[int],
                  frame: tuple[int, int]) -> str:
    """full-bleed / stage / punch, for one beat.

    Eligibility is about the ARTWORK, not the beat's class. Gating the punch
    on `is_data` made it unreachable: the assets a tighter crop suits are the
    1:1 drawings, and every one of those arrives as a punctuation beat, so
    three registers shipped as two and the punch was dead code.

    `punch_cycle` is a single-element counter that advances only on beats that
    COULD punch. Counting every beat instead left the cycle permanently out of
    phase with eligibility — a script whose croppable beats happened to land
    on indices 0, 3, 4 and 6 never punched once.
    """
    del is_data     # the drawing decides, not the beat's class
    if is_full_frame(asset, (frame[0], frame[1])):
        # It was drawn to BE the frame. Fitted into the stage box it becomes a
        # letterboxed thumbnail of a shot — the one thing it was built not to
        # be, and the reason eleven assets were unusable.
        return FULL_BLEED
    if not _is_croppable(asset):
        return STAGE
    punch_cycle[0] += 1
    return PUNCH if punch_cycle[0] % PUNCH_EVERY == 0 else STAGE


def _is_typeset(asset) -> bool:
    """A card that is text on paper rather than a drawing.

    The blank layouts declare `clear` on their boxes because their placeholder
    copy is baked into the PNG — which is also exactly what marks them as
    typesetting rather than artwork.
    """
    return asset is not None and any(s.clear for s in asset.slots)


def _is_croppable(asset) -> bool:
    """Whether tightening the frame on this asset keeps it readable.

    A punch is for a DRAWING: crop in on the figure and the beat gains
    emphasis. On a typeset card it destroys the layout — cropping a term card
    to 62% takes the definition off the bottom of the frame, which is exactly
    what it did to "Owner Earnings" and the dilution card.
    """
    if any(s.clear for s in asset.slots):
        return False          # the blank layouts are typeset, not drawn
    return asset.aspect == "1:1"


def _median_coverage(beats: list[dict], klass: str) -> float:
    """Median frame fraction for one class of beat, or 0.0 when there are none."""
    fracs = sorted(b["frac"] for b in beats if b.get("class") == klass)
    if not fracs:
        return 0.0
    mid = len(fracs) // 2
    if len(fracs) % 2:
        return round(fracs[mid], 4)
    return round((fracs[mid - 1] + fracs[mid]) / 2, 4)


def stage_box(W: int, H: int, px, *, is_data: bool) -> tuple[int, int]:
    """The box a beat is fitted into, before its aspect is known.

    The width is the frame's, not a landscape card's. `fit_to_frame` then
    decides per asset whether that width is usable.
    """
    if not is_data:
        return px(PUNCT_BOX), px(PUNCT_BOX)
    return min(px(STAGE_MAX_W), W), px(STAGE_H)


def fit_to_frame(img, box: tuple[int, int], W: int, H: int, px):
    """Fit a drawing to the FRAME's width when its shape allows it.

    A square or portrait drawing takes the full frame width and whatever
    height that needs, clamped to the stage band. A landscape one is
    contain-fitted as before, because widening it only adds empty margin.

    This is the single biggest change available to the short and it costs
    nothing: 134 of the kit's assets are 1:1, and every one of them was being
    contain-fitted into a 1000x760 landscape box — 760x760 on a 1080x1920
    frame, 28% of the screen, a card floating in paper.
    """
    if not img.width or not img.height:
        return img
    portraitish = img.height >= img.width * 0.98
    if not portraitish:
        return fit_into(img, *box)
    width = min(px(STAGE_MAX_W), W)
    height = int(img.height * width / img.width)
    limit = box[1]
    if height > limit:
        # Taller than the band: fall back to fitting the band's height, which
        # is still wider than the old landscape box for anything square.
        return fit_into(img, width, limit)
    return fit_into(img, width, height)


def _transform_for(register: str, asset, box, W: int, H: int, px):
    """The per-frame transform an animated beat needs for its register."""
    def framed(img):
        # The long-form cards carry their own chip and disclaimer; the short
        # draws both itself, so they come off before anything else happens.
        img = strip_baked_furniture(img, asset)
        if register == FULL_BLEED:
            return cover_on_paper(img, W, H)
        if register == PUNCH:
            return fit_into(punch_crop(img, asset), px(1040), px(STAGE_H + 200))
        return fit_to_frame(img, box, W, H, px)

    return framed


def _frame_for(img, register: str, box, y: int, W: int, H: int, px, asset=None,
               punct: bool = False):
    """(image, x, y) for a still in its register."""
    if register == FULL_BLEED:
        return cover_on_paper(img, W, H), 0, 0
    if register == PUNCH:
        # Placed relative to the band the beat belongs to, the same way the
        # clip path does it — a fixed y here dragged a punctuation beat up
        # into the stage and left the two paths disagreeing.
        punched = fit_into(punch_crop(img, asset), px(1040), px(STAGE_H + 200))
        x, top = _origin_for(PUNCH, punched.width, punched.height, y, W,
                             punct=punct)
        return punched, x, min(top, max(H - punched.height, 0))
    fitted = fit_to_frame(img, box, W, H, px)
    x, top = _origin_for(STAGE, fitted.width, fitted.height, y, W, punct=punct)
    return fitted, x, min(top, max(H - fitted.height, 0))


# How far a punctuation beat sits off the frame's centre line, as a fraction
# of the slack it has. A reaction is LAYERED over what is already up, so it
# reads as a comment on the frame rather than a replacement for it — and now
# that it is 760 rather than 520, centring it blanketed the gut check it was
# reacting to.
PUNCT_OFFSET = 0.62


def _origin_for(register: str, w: int, h: int, y: int, W: int,
                punct: bool = False) -> tuple[int, int]:
    """Where a rendered clip of width `w` sits, for its register."""
    if register == FULL_BLEED:
        return 0, 0
    slack = max(W - w, 0)
    x = int(slack * PUNCT_OFFSET) if punct else int(slack / 2)
    if register == PUNCH:
        return x, max(y - int(h * 0.12), 0)
    return x, y
