"""Where design's moves land in a SHORT, and what their frames look like.

The rules under test are the ones a viewer would notice being broken: a
number that counts up is the number being said, not the oldest year on the
sheet; two moves on one plate never play at once, and none is cut off by the
cut; the pen-circle is rare, never two shorts running, and never round a
figure that IS the plate (Valentin, 26 Sep 2026: "make it that he doesn't
abuse circling the whole plate, make it less frequent"); and a move that has
landed leaves the plate exactly as its still.
"""

from __future__ import annotations

import json
import re
from collections import namedtuple
from pathlib import Path

import pytest

from pipeline import motion as M
from pipeline import moves as MV

ROOT = Path(__file__).resolve().parents[1]
Word = namedtuple("Word", "word start end")


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir)


def _compose(fmt_name, settings, reg, tmp):
    """A fixture script's composition, cut exactly as the render cuts it."""
    from pipeline.compose import build_layers
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import (ShortResolver, build_anchors,
                                       prune_empty_shots)
    from pipeline.shots import (apply_order, choose_order, expand_sequences,
                                load_format, resolve_spans)
    from pipeline.tts import TTSEngine

    fixture = {"short": "short_valid", "earnings": "earnings_valid",
               "macro": "macro_valid"}[fmt_name]
    raw = (ROOT / "fixtures" / "scripts" / f"{fixture}.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short")
    resolver = ShortResolver(script=script, workdir=tmp, settings=settings,
                             prices=None, handle="@channel")
    fmt = load_format(fmt_name)
    fmt = apply_order(fmt, choose_order(fmt, seed=script.content_sha(), avoid=set()))
    fmt = expand_sequences(fmt, resolver.list_for)
    fmt, _ = prune_empty_shots(fmt, resolver)
    spans = resolve_spans(fmt, tts.words, tts.duration_s, build_anchors(script))
    result = build_layers(fmt, spans, resolver, reg, aspect=fmt.aspect,
                          seed=script.content_sha(), avoid=set())
    return fmt, result, list(tts.words), script


@pytest.fixture(scope="module")
def short(settings, reg, tmp_path_factory):
    return _compose("short", settings, reg, tmp_path_factory.mktemp("short"))


@pytest.fixture(scope="module", params=["short", "earnings", "macro"])
def vertical(request, settings, reg, tmp_path_factory):
    return _compose(request.param, settings, reg,
                    tmp_path_factory.mktemp(request.param))


def _plans(fmt, result, words, reg, settings, n=40):
    return [MV.plan_short(fmt, result, reg, words, seed=f"video-{i}",
                          settings=settings) for i in range(n)]


# ---------------------------------------------------------------------------
# What counts up
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("$3.1bn", True), ("−40%", True), ("+2.6pt", True), ("12,400", True),
    ("-$71M", True), ("5×", True), ("(12.5)", True), ("496", True),
    ("FY2025", False), ("today · 5× average volume", False), ("Revenue", False),
    ("$400M to $496M", False), ("", False), ("Q3", False),
])
def test_only_a_slot_holding_one_figure_counts_up(text, want):
    assert MV.is_one_figure(text) is want


def test_a_figure_states_its_signed_number():
    assert MV.figure_number("-$71M") == -71
    assert MV.figure_number("−18.4%") == -18.4
    assert MV.figure_number("$496M") == 496
    assert MV.figure_number("1,234") == 1234
    assert MV.figure_number("words") is None


def test_a_sheet_counts_the_latest_figure_of_the_row_it_lights(reg):
    """Design's anchor on every sheet is the first cell, the oldest year —
    the one number nobody is talking about."""
    plate = reg.get("tables/numbers-sheet-3r-9x16")
    values = {f"cell-{r}-{c}": str(r * 100 + c) for r in (1, 2, 3) for c in range(1, 7)}
    assert MV._figure_slots(plate, values, "band-2") == ["cell-2-6"]
    assert MV._figure_slots(plate, values, "all") == []
    assert MV._figure_slots(plate, values, "") == []


def test_every_count_up_lands_on_the_figure_the_slot_holds(short, reg, settings):
    fmt, result, words, _ = short
    plan = MV.plan_short(fmt, result, reg, words, seed="x", settings=settings)
    values = {l.name: l.values for l in result.layers if l.kind == "plate"}
    counted = [m for m in plan.moves if m.move == "count-up"]
    assert counted, "a short with figures on screen counted none of them up"
    for m in counted:
        assert m.text == values[m.layer][m.slot]
        assert M.count_text(m.text, 1.0).replace(",", "") \
            .lstrip("0") in m.text.replace(",", "")
        assert not m.slot.endswith("-1") or not m.slot.startswith("cell-")


# ---------------------------------------------------------------------------
# One at a time, and inside the shot
# ---------------------------------------------------------------------------

def test_moves_on_one_plate_never_overlap_and_all_finish_before_the_cut(vertical, reg,
                                                                      settings):
    fmt, result, words, _ = vertical
    spans = {sp.shot.id: sp for sp in result.spans}
    for plan in _plans(fmt, result, words, reg, settings, n=12):
        by_layer: dict[str, list] = {}
        for m in plan.moves:
            by_layer.setdefault(m.layer, []).append(m)
            sp = spans[m.shot_id]
            assert m.start >= sp.start - 1e-9, m
            assert m.end <= sp.end - MV.END_MARGIN_S + 1e-9, m
        for moves in by_layer.values():
            moves.sort(key=lambda m: m.start)
            for a, b in zip(moves, moves[1:]):
                assert b.start >= a.end + MV.MOVE_GAP_S - 1e-9, (a, b)


def test_one_emphasis_per_shot_at_most(vertical, reg, settings):
    fmt, result, words, _ = vertical
    for plan in _plans(fmt, result, words, reg, settings, n=12):
        per_shot: dict[str, int] = {}
        for m in plan.moves:
            if m.move in ("pen-circle", "zoom-to-slot") or (
                    m.move == "highlight" and not m.slot.startswith("band-")):
                per_shot[m.shot_id] = per_shot.get(m.shot_id, 0) + 1
        assert all(n == 1 for n in per_shot.values()), per_shot


# ---------------------------------------------------------------------------
# The circle
# ---------------------------------------------------------------------------

def test_the_circle_plays_in_about_one_short_in_three():
    got = sum(MV._circle_this_video(f"video-{i}", False) for i in range(900))
    assert 240 <= got <= 360, got


def test_the_circle_never_plays_two_shorts_running():
    assert not any(MV._circle_this_video(f"video-{i}", True) for i in range(300))


def test_the_circle_plays_at_most_once_and_only_on_a_verdict_shot(vertical, reg,
                                                                  settings):
    fmt, result, words, _ = vertical
    plans = _plans(fmt, result, words, reg, settings, n=60)
    for plan in plans:
        rings = [m for m in plan.moves if m.move == "pen-circle"]
        assert len(rings) <= 1
        assert all(m.shot_id in MV.CIRCLE_SHOTS for m in rings)
    rate = sum(any(m.move == "pen-circle" for m in p.moves) for p in plans) / len(plans)
    assert rate <= 0.5, f"the circle played in {rate:.0%} of sixty shorts"


def test_the_circle_never_rings_a_figure_that_fills_its_plate(reg, settings):
    """big-number sets its figure across the frame: a ring round it is a ring
    round the plate. A cell on a full sheet is what the pen is for."""
    big = reg.get("figures/big-number-l2-9x16")
    assert MV.circle_box(big, "value", "$496M", settings, reg) is None
    sheet = reg.get("tables/numbers-sheet-4r-9x16")
    box = MV.circle_box(sheet, "cell-1-6", "496", settings, reg)
    assert box is not None
    cw, ch = sheet.canvas
    assert box.w * box.h <= cw * ch * MV.CIRCLE_MAX_AREA


def test_every_ring_ever_drawn_is_a_small_part_of_its_plate(vertical, reg, settings):
    fmt, result, words, _ = vertical
    values = {l.name: (l.entry_key, l.values) for l in result.layers if l.kind == "plate"}
    for plan in _plans(fmt, result, words, reg, settings, n=60):
        for m in plan.moves:
            if m.move != "pen-circle":
                continue
            key, vals = values[m.layer]
            plate = reg.get(key)
            box = MV.circle_box(plate, m.slot, vals[m.slot], settings, reg)
            assert box is not None
            ring = M.pen_circle(box, m.seed)
            xs = [p[0] for p in ring.points]
            ys = [p[1] for p in ring.points]
            cw, ch = plate.canvas
            assert (max(xs) - min(xs)) <= cw * 0.75 and (max(ys) - min(ys)) <= ch * 0.3


def test_on_the_sheet_the_circle_rings_the_figure_the_payoff_says(short, reg, settings):
    fmt, result, words, _ = short
    payoff = MV.shot_plates(result)["payoff"]
    sheet = MV.shot_plates(result)["the-sheet"]
    for plan in _plans(fmt, result, words, reg, settings, n=60):
        for m in plan.moves:
            if m.move == "pen-circle" and m.shot_id == "the-sheet":
                assert MV.figure_number(sheet.values[m.slot]) == \
                    MV.figure_number(payoff.values["value"])


def test_a_circle_that_sits_out_says_why(short, reg, settings):
    fmt, result, words, _ = short
    plans = _plans(fmt, result, words, reg, settings, n=30)
    for plan in plans:
        if not any(m.move == "pen-circle" for m in plan.moves):
            assert plan.skipped, "a circle that did not play left no reason"


# ---------------------------------------------------------------------------
# Wipes
# ---------------------------------------------------------------------------

def _with_enter(fmt, ids, enter="wipe"):
    from dataclasses import replace

    return replace(fmt, shots=tuple(replace(s, enter=enter) if s.id in ids else s
                                    for s in fmt.shots))


def test_a_wipe_goes_only_on_a_cut_the_template_marks(short, reg, settings):
    from dataclasses import replace

    fmt, result, words, _ = short
    by_id = {sp.shot.id: sp.shot for sp in result.spans}
    for w in MV.plan_wipes(fmt, result, reg, seed="x"):
        assert (by_id[w.shot_in].enter or "").startswith("wipe")
    marked = ("the-news", "numbers-1", "the-comment", "payoff")
    spans = [replace(sp, shot=replace(sp.shot, enter="wipe")) if sp.shot.id in marked
             else replace(sp, shot=replace(sp.shot, enter=None)) for sp in result.spans]
    result2 = replace(result, spans=spans)
    wipes = MV.plan_wipes(fmt, result2, reg, seed="x", max_wipes=3)
    assert 1 <= len(wipes) <= 3
    assert {w.shot_in for w in wipes} <= set(marked)
    keys = [w.key for w in wipes]
    assert all(a != b for a, b in zip(keys, keys[1:])), "two wipes in a row are one move"
    for w in wipes:
        # the cover is full on the frame the cut is under
        assert w.frame_at(w.cut) == w.cut_frame
        assert w.frame_at(w.start) == 0 and w.frame_at(w.end) is None


def test_every_short_wipes_two_or_three_changes_of_subject(vertical, reg, settings):
    """Item 13: a few signposts, never one inside a sequence."""
    fmt, result, words, _ = vertical
    wipes = MV.plan_wipes(fmt, result, reg, seed="x")
    assert 2 <= len(wipes) <= 3, [w.shot_in for w in wipes]
    beat = lambda shot_id: re.sub(r"(-\d+)?(-in)?$", "", shot_id)  # noqa: E731
    for w in wipes:
        assert beat(w.shot_out) != beat(w.shot_in), f"{w.shot_in}: a wipe inside a sequence"


def test_moves_wait_for_the_wipe_to_uncover_the_shot(short, reg, settings):
    from dataclasses import replace

    fmt, result, words, _ = short
    spans = [replace(sp, shot=replace(sp.shot, enter="wipe"))
             if sp.shot.id == "the-news" else sp for sp in result.spans]
    result2 = replace(result, spans=spans)
    plan = MV.plan_short(fmt, result2, reg, words, seed="x", settings=settings)
    wipe = next(w for w in plan.wipes if w.shot_in == "the-news")
    for m in plan.moves:
        if m.shot_id == "the-news":
            assert m.start >= wipe.cut + MV.AFTER_WIPE_S - 1e-9


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

def test_the_record_is_what_the_sound_reads(short, reg, settings):
    from pipeline.sound import Move

    fmt, result, words, _ = short
    plan = MV.plan_short(fmt, result, reg, words, seed="x", settings=settings)
    rec = json.loads(json.dumps(plan.record()))
    assert rec["moves"] and set(rec) == {"moves", "wipes", "skipped"}
    starts = [r["start"] for r in rec["moves"]]
    assert starts == sorted(starts)
    for r in rec["moves"]:
        Move(r["move"], r["start"], r["shot_id"], r["slot"])
        assert r["move"] in MV._CATALOGUE or r["move"] == "slide-in"


def test_recent_moves_reads_the_last_render_and_never_its_own(tmp_path, settings):
    from dataclasses import replace

    from pipeline.reach import recent_moves

    s = settings.model_copy(update={"workspace_dir": tmp_path})
    a = tmp_path / "EXMPL" / "2026-09-25"
    b = tmp_path / "OTHER" / "2026-09-26"
    for ws, moves in ((a, ["pen-circle", "count-up"]), (b, ["count-up"])):
        ws.mkdir(parents=True)
        (ws / "short_final.manifest.json").write_text(json.dumps(
            {"moves": {"moves": [{"move": m, "start": 1.0} for m in moves]}}))
    import os
    os.utime(a / "short_final.manifest.json", (1, 1))
    assert recent_moves(s, window=1) == {"count-up"}
    assert recent_moves(s, window=1, exclude=b) == {"pen-circle", "count-up"}
    assert MV.recent_circled(s, exclude=b) is True
    assert MV.recent_circled(s) is False
    (tmp_path / "old" / "x").mkdir(parents=True)
    (tmp_path / "old" / "x" / "a.manifest.json").write_text("{}")
    assert "pen-circle" in recent_moves(s, window=3)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _layer(result, shot_id):
    return MV.shot_plates(result)[shot_id]


def _diff(a, b) -> float:
    import numpy as np

    x = np.asarray(a.convert("RGBA"), dtype=np.int16)
    y = np.asarray(b.convert("RGBA"), dtype=np.int16)
    return float(np.abs(x - y).mean())


def test_a_landed_count_up_leaves_the_plate_as_its_still(short, reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    fmt, result, words, _ = short
    layer = _layer(result, "the-move")
    move = MV.Move("count-up", "the-move", layer.name, "value", layer.t_start, 7,
                   "out", text=layer.values["value"])
    cache = _Cache(settings, reg)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg, settings, cache)
    still = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    still.alpha_composite(cache.plate(layer.entry_key, 0, layer.values, layer.w, layer.h),
                          (layer.x, layer.y))
    landed = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_layer(landed, layer, move.end + 1.0, 0)
    assert _diff(still, landed) < 0.5
    first = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_layer(first, layer, move.start, 0)
    assert _diff(still, first) > _diff(still, landed)
    before = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_layer(before, layer, move.start - 0.5, 0)
    assert before.getbbox() is not None


def test_a_row_band_sweeps_in_from_the_left(short, reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    fmt, result, words, _ = short
    layer = _layer(result, "numbers-1")
    move = MV.Move("highlight", "numbers-1", layer.name, "band-1", layer.t_start, 6, "out")
    cache = _Cache(settings, reg)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg, settings, cache)
    plate = reg.get(layer.entry_key)
    band = plate.slots["band-1"]
    k = layer.w / plate.canvas[0]
    frames = []
    for f in range(6):
        img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        comp.draw_layer(img, layer, move.start + (f + 0.5) / 12, 0)
        frames.append(img)
    still = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    still.alpha_composite(cache.plate(layer.entry_key, 0, layer.values, layer.w, layer.h),
                          (layer.x, layer.y))
    box = (int(layer.x + band.x * k), int(layer.y + band.y * k),
           int(layer.x + (band.x + band.w) * k), int(layer.y + (band.y + band.h) * k))
    diffs = [_diff(fr.crop(box), still.crop(box)) for fr in frames]
    assert diffs[0] > diffs[-1]
    assert diffs[-1] < 0.5


def test_the_ring_is_drawn_round_the_figure_not_the_slot(short, reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    fmt, result, words, _ = short
    layer = _layer(result, "the-sheet")
    slot = "cell-1-6"
    move = MV.Move("pen-circle", "the-sheet", layer.name, slot, layer.t_start, 8, "inOut")
    cache = _Cache(settings, reg)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg, settings, cache)
    still = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    still.alpha_composite(cache.plate(layer.entry_key, 0, layer.values, layer.w, layer.h),
                          (layer.x, layer.y))
    ringed = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_layer(ringed, layer, move.end + 0.5, 0)
    import numpy as np

    d = np.abs(np.asarray(ringed, dtype=np.int16) - np.asarray(still, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d > 40)
    assert len(xs), "no ring was drawn"
    plate = reg.get(layer.entry_key)
    k = layer.w / plate.canvas[0]
    box = MV.circle_box(plate, slot, layer.values[slot], settings, reg)
    cx, cy = layer.x + (box.x + box.w / 2) * k, layer.y + (box.y + box.h / 2) * k
    assert abs(xs.mean() - cx) < 30 and abs(ys.mean() - cy) < 30
    assert (xs.max() - xs.min()) < (box.w + 120) * k


def test_a_wipe_covers_the_whole_frame_on_the_cut(reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    key = reg.aspect_key("overlays/wipe-sweep", "9x16")
    plate = reg.get(key)
    assert plate is not None and (plate.transition or {}).get("frames") == 8
    w = MV.Wipe(key=key, cut=5.0, shot_out="a", shot_in="b")
    comp = MV.MoveCompositor(MV.MovePlan(wipes=[w]), reg, settings, _Cache(settings, reg))
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_overlays(img, w.cut + 0.01)
    import numpy as np

    # Every pixel is covered. Design's hatch on the cover is drawn in partial
    # opacity (down to a quarter), so the cut ghosts through about 2% of the
    # frame for one frame; that is theirs to fix and is in the note to them.
    alpha = np.asarray(img)[:, :, 3]
    assert (alpha > 0).mean() > 0.999, "the cut shows through the cover"
    assert (alpha > 128).mean() > 0.99


# ---------------------------------------------------------------------------
# The hook (item 6)
# ---------------------------------------------------------------------------

def test_the_hook_card_carries_the_day_s_move_in_its_own_slot(settings):
    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import ShortResolver

    raw = (ROOT / "fixtures" / "scripts" / "short_valid.json").read_text(encoding="utf-8")
    script, _ = parse_short_script(raw, settings)
    r = ShortResolver(script=script, workdir=ROOT, settings=settings, prices=None,
                      handle="@channel")
    assert script.move_summary.startswith("+29%")
    assert r.text_for("chart.move") == "+29%"
    assert r.text_for("chart.move_rest") == "today · 5× average volume"
    flat = script.model_copy(update={"move_summary": "Q3 beat · guide raised"})
    r2 = ShortResolver(script=flat, workdir=ROOT, settings=settings, prices=None,
                       handle="@channel")
    assert r2.text_for("chart.move") is None
    assert r2.text_for("chart.move_rest") == "Q3 beat · guide raised"


@pytest.mark.parametrize("name", ["short", "earnings", "macro"])
def test_every_hook_card_with_a_move_slot_binds_it(name, reg):
    from pipeline.shots import load_format

    fmt = load_format(name)
    hook = fmt.shots[0]
    for plate, bind in [(hook.plate, hook.bind)] + [(a.plate, a.bind or hook.bind)
                                                     for a in hook.alts]:
        key = reg.aspect_key(plate, "9x16") or plate
        slots = reg.get(key).slots
        if "move" in slots:
            assert bind.get("move") == "?chart.move", plate
            assert bind.get("sub") == "?chart.move_rest", plate
        else:
            assert "move" not in bind and bind.get("sub") == "?script.move_summary", plate


def test_the_hook_s_move_counts_up_as_the_short_opens(short, reg, settings):
    fmt, result, words, _ = short
    hook = result.spans[0]
    layer = MV.shot_plates(result)[hook.shot.id]
    plan = MV.plan_short(fmt, result, reg, words, seed="x", settings=settings)
    if "move" not in layer.values:
        pytest.skip(f"{layer.entry_key} has no move slot")
    assert layer.values["move"] == "+29%"
    count = next(m for m in plan.moves if m.layer == layer.name and m.slot == "move")
    assert count.move == "count-up" and count.start == pytest.approx(layer.t_start)
    assert count.end - layer.t_start <= 0.6 + 1e-9
