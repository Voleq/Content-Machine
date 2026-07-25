"""SHORT scene engine — 9:16, ~55–60s "Noise or signal?" (§4).

A TEMPLATE FILLER over the fixed reusable asset kit: every video reuses
the same branded chart component, headline-overlay treatment, numbers
sheet, caption style, hand-drawn annotations, transition stingers,
intro/outro bug and music bed — only the rotating content changes
(ticker, price data, headlines, numbers, hook, memes).

Fixed beats, each with its own on-screen element:
  Hook      — the branded chart (rendered HERE from our own price data —
              never a screenshot) + the mute-safe hook card
  Why       — driver headline(s) overlaid ON the chart
  Gut check — the multi-year numbers sheet, rows typing on, trend bars
  Payoff    — the deadpan conclusion card (no verdict, no stamp)

Every visual event's time comes from `build_short_timeline` (the master
clock); this module only turns cues into rasters, alpha clips and one
FFmpeg filtergraph. There are NO hardcoded scene timings here — grep for
`between(t` lands only on cue-derived values.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from config import Settings
from pipeline.broll import ContentManager
from pipeline.chart import render_marker_price_chart, render_price_chart
from pipeline.models import ChartStyle, CueKind, ScribbleStyle, ShortScript, TTSResult, parse_scribble_payload
from pipeline.prices import PriceSeries, get_price_history
from pipeline.rasters import (
    GREEN,
    INK,
    RED,
    SHANTELL,
    brand_bug,
    build_karaoke_ass,
    doodle_clip,
    flash_frames,
    frames_to_alpha_clip,
    headline_card,
    lower_third,
    nos_header,
    number_row_frames,
    number_row_image,
    numbers_sheet_base,
    scribble_callout_frames,
    scribble_frames,
    simple_text,
    text_panel,
    ticker_pill,
    zoom_pop_frames,
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


# Per-beat layout variants from the design kit's Short Variants sheet. The
# timeline picks one per beat from the script hash (see `pick_beat_variant`),
# so two shorts cut on the same day do not share a layout while any single
# script always renders identically. Coordinates are in the 1080-wide design
# space and scaled to the output resolution.
HOOK_LAYOUTS: dict[str, dict] = {
    "a": {"y": 1040, "size": 60, "width": 960, "accent": GREEN},   # the original
    "b": {"y": 300, "size": 76, "width": 920, "accent": RED},      # hook up top
    "c": {"y": 1180, "size": 54, "width": 980, "accent": INK},     # low and wide
    "d": {"y": 240, "size": 66, "width": 880, "accent": RED},      # narrow, high
    "e": {"y": 980, "size": 68, "width": 940, "accent": GREEN},    # centre-low
}
NUMBERS_LAYOUTS: dict[str, dict] = {
    "a": {"y": 990, "width": 1000},
    "b": {"y": 900, "width": 1000},
    "c": {"y": 1050, "width": 960},
    "d": {"y": 940, "width": 980},
}
PAYOFF_LAYOUTS: dict[str, dict] = {
    "a": {"y": 430, "size": 48, "accent": GREEN},
    "b": {"y": 620, "size": 52, "accent": RED},
    "c": {"y": 360, "size": 46, "accent": INK},
    "d": {"y": 540, "size": 50, "accent": GREEN},
    "e": {"y": 700, "size": 44, "accent": RED},
}


def _layout(table: dict[str, dict], variant: str | None) -> dict:
    """The layout for a beat variant, falling back to the original."""
    return table.get(variant or "a", table["a"])


def sample_hook_opener(script_sha: str, settings: Settings) -> str:
    """Deterministically sample the hook bank (seeded by the script sha so
    re-renders are idempotent, different scripts get fresh openers)."""
    bank_file = settings.assets_dir / "hook_bank.json"
    try:
        openers = json.loads(bank_file.read_text()).get("openers") or []
    except (FileNotFoundError, json.JSONDecodeError):
        openers = []
    if not openers:
        return settings.brand_tagline
    idx = int(hashlib.sha256(f"hook|{script_sha}".encode()).hexdigest()[:8], 16)
    return openers[idx % len(openers)]


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
    content = content or ContentManager(settings)
    prices = prices or get_price_history(script.ticker, settings)

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

    hook = next(c for c in cues if c.kind is CueKind.HOOK)
    numbers = next(c for c in cues if c.kind is CueKind.NUMBERS)
    conclusion = next(c for c in cues if c.kind is CueKind.CONCLUSION)
    transitions = [c for c in cues if c.kind is CueKind.TRANSITION]
    headline_cues = [c for c in cues if c.kind is CueKind.HEADLINE]
    row_cues = [c for c in cues if c.kind is CueKind.NUMBER_ROW]
    annotation_cues = [c for c in cues if c.kind is CueKind.ANNOTATION]
    zoom_cues = [c for c in cues if c.kind is CueKind.ZOOM]
    meme_cues = [c for c in cues if c.kind is CueKind.MEME]
    cutaway_cues = [c for c in cues if c.kind is CueKind.CUTAWAY]
    doodle_cues = [c for c in cues if c.kind is CueKind.DOODLE]
    scribble_cues = [c for c in cues if c.kind is CueKind.SCRIBBLE]

    layers: list[OverlayLayer] = []

    # ------------------------------------------- the branded chart (hero)
    # open on the clean branded card or the crude marker/napkin chart
    chart_px = (px(1000), px(760))
    chart_pos = (px(40), px(170))
    render_chart = (render_marker_price_chart
                    if script.chart_style is ChartStyle.MARKER else render_price_chart)
    chart_path, chart_meta = render_chart(
        prices, rdir / "chart.png", settings,
        size=chart_px, move_text=script.move_summary,
    )
    layers.append(OverlayLayer(
        path=chart_path, x=chart_pos[0], y=chart_pos[1],
        t_start=0.0, t_end=duration, name="chart",
    ))

    # ------------------------------------------------------ intro/outro bug
    opener = sample_hook_opener(script.content_sha(), settings)
    bug = brand_bug(settings, opener, width=px(900), font_size=px(40))
    bug_path = rdir / "bug.png"
    bug.save(bug_path)
    layers.append(OverlayLayer(
        path=bug_path, x=int((W - bug.width) / 2), y=px(48),
        t_start=0.0, t_end=duration, name="brand_bug",
    ))

    # ------------------------------------------------------------ hook card
    hook_layout = _layout(HOOK_LAYOUTS, hook.payload.get("variant"))
    hook_img = text_panel(settings, hook.payload["text"], width=px(hook_layout["width"]),
                          font_name=SHANTELL, font_size=px(hook_layout["size"]),
                          accent=hook_layout["accent"])
    hook_path = rdir / "hook.png"
    hook_img.save(hook_path)
    layers.append(OverlayLayer(
        path=hook_path, x=int((W - hook_img.width) / 2), y=px(hook_layout["y"]),
        t_start=0.0, t_end=float(hook.payload["until"]), name="hook",
    ))

    # -------------------------------- $TICKER pill + "noise or signal?" header
    pill = ticker_pill(settings, script.ticker, font_size=px(40))
    pill_path = rdir / "ticker_pill.png"
    pill.save(pill_path)
    layers.append(OverlayLayer(
        path=pill_path, x=px(40), y=px(150), t_start=0.0, t_end=duration,
        name="ticker_pill",
    ))
    nos = nos_header(settings, font_size=px(30))
    nos_path = rdir / "nos_header.png"
    nos.save(nos_path)
    layers.append(OverlayLayer(
        path=nos_path, x=W - nos.width - px(40), y=px(156),
        t_start=0.0, t_end=duration, name="nos_header",
    ))

    # ------------------------------------- headlines overlaid ON the chart
    slots = chart_meta["headline_slots"]
    for c in headline_cues:
        i = int(c.payload["index"])
        meaning = script.headlines[i].meaning if i < len(script.headlines) else ""
        card = headline_card(settings, c.payload["text"], meaning=meaning,
                             width=px(880), font_size=px(34))
        card_path = rdir / f"headline_{i}.png"
        card.save(card_path)
        sx, sy = slots[min(i, len(slots) - 1)]
        layers.append(OverlayLayer(
            path=card_path,
            x=chart_pos[0] + int(sx), y=chart_pos[1] + int(sy),
            t_start=c.t, t_end=float(c.payload["until"]),
            fade_in=0.18, name=f"headline_{i}",
        ))

    # -------------------------------------------------- the numbers sheet
    sheet_layout = _layout(NUMBERS_LAYOUTS, numbers.payload.get("variant"))
    sheet_img, layout = numbers_sheet_base(
        settings, len(script.numbers), script.years, width=px(sheet_layout["width"]),
    )
    sheet_path = rdir / "sheet.png"
    sheet_img.save(sheet_path)
    sheet_pos = (px(40), px(sheet_layout["y"]))
    layers.append(OverlayLayer(
        path=sheet_path, x=sheet_pos[0], y=sheet_pos[1],
        t_start=numbers.t, t_end=duration, fade_in=0.2, name="numbers_sheet",
    ))

    row_geo: dict[int, tuple[int, int]] = {}
    for c in row_cues:
        i = int(c.payload["index"])
        clip = frames_to_alpha_clip(
            number_row_frames(settings, c.payload["label"], c.payload["values"],
                              layout, fps=settings.fps,
                              type_seconds=float(c.payload["type_seconds"])),
            settings.fps, rdir / f"row_{i}.mov",
        )
        ry = sheet_pos[1] + layout["rows_y0"] + i * layout["row_h"]
        row_geo[i] = (sheet_pos[0], ry)
        layers.append(OverlayLayer(
            path=clip, x=sheet_pos[0], y=ry,
            t_start=c.t, t_end=duration, is_video=True, hold=True,
            name=f"number_row_{i}",
        ))

    # ------------------------- hand-drawn scribbles (chart & numbers rows)
    for k, c in enumerate(annotation_cues):
        target = c.payload["target"]
        if target == "chart":
            lx, ly = chart_meta["last_point"]
            sw, sh = px(240), px(190)
            x = chart_pos[0] + int(lx) - sw // 2
            y = chart_pos[1] + int(ly) - sh // 2
            t_end = numbers.t if c.t < numbers.t else duration
        else:
            i = int(c.payload["row_index"] or 0)
            rx, ry = row_geo.get(i, (sheet_pos[0], sheet_pos[1]))
            sw, sh = px(1000), layout["row_h"]
            x, y = rx, ry
            t_end = duration
        # keep the scribble fully on-canvas (the chart's last point sits
        # near the right edge)
        x = min(max(x, px(6)), W - sw - px(6))
        y = min(max(y, px(6)), H - sh - px(6))
        clip = frames_to_alpha_clip(
            scribble_frames(sw, sh, style="circle", fps=settings.fps,
                            seed=f"{script.ticker}|{k}"),
            settings.fps, rdir / f"scribble_{k}.mov",
        )
        layers.append(OverlayLayer(
            path=clip, x=x, y=y,
            t_start=c.t, t_end=t_end, is_video=True, hold=True,
            name=f"scribble_{k}_{target}",
        ))
        note = (c.payload.get("note") or "").strip()
        if note:
            note_img = simple_text(settings, note, font_size=px(34),
                                   fill=(*RED, 255), stroke_width=2)
            note_path = rdir / f"note_{k}.png"
            note_img.save(note_path)
            if target == "chart":
                # under the circled point, hugging the chart's right edge
                nx = min(x + sw // 2 - note_img.width // 2,
                         W - note_img.width - px(16))
                ny = min(y + sh + px(4), H - note_img.height - px(10))
            else:
                # in the bars zone above the row's right end — clear of the
                # neighbouring row's label
                nx = W - note_img.width - px(56)
                ny = y - note_img.height + px(10)
            layers.append(OverlayLayer(
                path=note_path, x=max(nx, px(10)), y=max(ny, px(10)),
                t_start=c.t, t_end=t_end, fade_in=0.15, name=f"note_{k}",
            ))

    # ------------------------------------- zoom-punch on the key number(s)
    for k, c in enumerate(zoom_cues):
        i = int(c.payload["row_index"])
        row_img = number_row_image(settings, script.numbers[i].label,
                                   script.numbers[i].values, layout)
        pop = zoom_pop_frames(row_img, fps=settings.fps)
        clip = frames_to_alpha_clip(pop, settings.fps, rdir / f"zoom_{k}.mov")
        rx, ry = row_geo.get(i, sheet_pos)
        cw, ch = pop[0].size
        layers.append(OverlayLayer(
            path=clip, x=int(rx - (cw - px(1000)) / 2),
            y=int(ry - (ch - layout["row_h"]) / 2),
            t_start=c.t, t_end=min(c.t + 0.6, duration), is_video=True,
            name=f"zoom_{k}",
        ))

    # ----------------------------------------------- meme freeze / cutaway
    for k, c in enumerate(meme_cues):
        meme = content.resolve_meme(c.payload["key"])
        from PIL import Image, ImageOps

        m = Image.open(meme.path).convert("RGB")
        m.thumbnail((px(880), px(700)), Image.LANCZOS)
        framed = ImageOps.expand(m, border=px(14), fill=(245, 245, 245))
        meme_path = rdir / f"meme_{k}.png"
        framed.save(meme_path)
        hold = float(c.payload["duration"])
        layers.append(OverlayLayer(
            path=meme_path, x=int((W - framed.width) / 2),
            y=px(480) - framed.height // 2 + px(200),
            t_start=c.t, t_end=min(c.t + hold, duration), name=f"meme_{k}",
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
    # rotate through a few slots so consecutive doodles don't stack
    doodle_slots = [(px(560), px(560)), (px(120), px(600)), (px(540), px(1180)),
                    (px(120), px(1180))]
    for k, c in enumerate(doodle_cues):
        visual = content.resolve_doodle(c.payload["value"])
        if visual is None:
            log.warning("doodle %r not resolved — skipped", c.payload["value"])
            continue
        hold = float(c.payload.get("hold", 1.6))
        clip, (cw, ch) = doodle_clip(
            visual.path, rdir / f"doodle_{k}.mov",
            display_w=px(380), duration_s=hold + 0.2, fps=settings.fps,
            seed=f"{script.ticker}|doodle|{k}",
        )
        sx, sy = doodle_slots[k % len(doodle_slots)]
        layers.append(OverlayLayer(
            path=clip, x=min(sx, W - cw), y=min(sy, H - ch),
            t_start=c.t, t_end=min(c.t + hold, duration),
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
            fps=settings.fps, hold_seconds=hold, seed=f"{script.ticker}|scr|{k}",
        )
        clip = frames_to_alpha_clip(frames, settings.fps, rdir / f"scribble_inline_{k}.mov")
        layers.append(OverlayLayer(
            path=clip, x=int((W - sw) / 2), y=px(560),
            t_start=c.t, t_end=min(c.t + hold + 0.5, duration),
            is_video=True, hold=True, name=f"scribble_inline_{k}",
        ))

    # ------------------------------------------- beat-transition stingers
    flash = frames_to_alpha_clip(
        flash_frames(W, H, fps=settings.fps), settings.fps, rdir / "flash.mov",
    )
    for c in transitions:
        if c.t <= 0.05:
            continue
        layers.append(OverlayLayer(
            path=flash, x=0, y=0, t_start=c.t,
            t_end=min(c.t + 0.2, duration), is_video=True,
            name=f"flash_{c.payload['name']}",
        ))

    # ------------------------------- cheap or trap: the value-trap beat
    # Held for SHORT_MIN_READABLE_S by the timeline — this is the one card in
    # a short the viewer is expected to read rather than glance at.
    for c in (c for c in cues if c.kind is CueKind.CHEAP_OR_TRAP):
        trap_img = text_panel(settings, c.payload["text"], width=px(980),
                              font_name=SHANTELL, font_size=px(46), accent=RED,
                              bg=(12, 12, 14, 240))
        trap_path = rdir / "cheap_or_trap.png"
        trap_img.save(trap_path)
        layers.append(OverlayLayer(
            path=trap_path, x=int((W - trap_img.width) / 2), y=px(560),
            t_start=c.t, t_end=float(c.payload["until"]), fade_in=0.25,
            name="cheap_or_trap",
        ))

    # ------------------------------------------------- the payoff card
    payoff_layout = _layout(PAYOFF_LAYOUTS, conclusion.payload.get("variant"))
    conc_img = text_panel(settings, conclusion.payload["text"], width=px(960),
                          font_name=SHANTELL, font_size=px(payoff_layout["size"]),
                          accent=payoff_layout["accent"], bg=(12, 12, 14, 245))
    conc_path = rdir / "conclusion.png"
    conc_img.save(conc_path)
    layers.append(OverlayLayer(
        path=conc_path, x=int((W - conc_img.width) / 2), y=px(payoff_layout["y"]),
        t_start=conclusion.t, t_end=duration, fade_in=0.25, name="conclusion",
    ))

    # a deadpan mascot rides the payoff — the reaction-head stickman
    mascot = content.resolve_doodle("reactions/deadpan")
    if mascot is not None:
        mclip, (mcw, mch) = doodle_clip(
            mascot.path, rdir / "mascot.mov",
            display_w=px(220), duration_s=max(duration - conclusion.t, 0.5),
            fps=settings.fps, seed=f"{script.ticker}|mascot",
        )
        layers.append(OverlayLayer(
            path=mclip, x=W - mcw - px(70), y=px(800),
            t_start=conclusion.t, t_end=duration, is_video=True, name="mascot",
        ))

    # -------------------------------------------------------- disclaimer
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
        tts.words, play_res=(W, H), font_size=px(62), margin_v=px(120),
        duration=duration,
    ))

    # ------------------------------------------------------------- audio
    audio = [AudioTrack(path=tts.audio_path, start_s=0.0, gain_db=0.0)]
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
    # a subtle, slow Ken Burns drift on the branded backdrop so the SHORT is
    # never a dead static hold (the fixed beat UI composites over it); ~6%
    # over the whole runtime — designed, not busy
    bg = settings.assets_dir / "backgrounds" / "dennis_bg_tall.png"
    zw = int(W * 1.06) // 2 * 2
    dur = max(duration, 0.1)
    base_ken_burns = (
        f"scale={zw}:-2,crop={W}:{H}:x='(iw-ow)*t/{dur:.3f}':y='(ih-oh)*t/{dur:.3f}',"
        f"setsar=1,format=yuv420p"
    )
    spec = CompositeSpec(
        base_input_args=[
            "-loop", "1", "-framerate", str(settings.fps),
            "-t", f"{duration:.3f}", "-i", str(bg),
        ],
        base_filter=base_ken_burns,
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
        "duration": duration,
        "opener": opener,
        "chart": {"source": prices.source, "degraded": prices.degraded,
                  "direction": chart_meta["direction"],
                  "style": script.chart_style.value},
        "cues": [c.model_dump() for c in cues],
        "layers": [
            {"name": l.name, "t_start": l.t_start, "t_end": l.t_end, "x": l.x, "y": l.y}
            for l in layers
        ],
        "filter_script": str(out_path.with_suffix(".filter.txt")),
        "output": str(out_path),
    }, indent=2))
    return out_path, manifest_path
