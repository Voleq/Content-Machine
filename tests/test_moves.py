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
    """Design's anchor on a sheet is the latest figure of its first row; a
    short counts the latest figure of the row it lights, which is the row
    being read."""
    plate = reg.get("tables/numbers-sheet-3r-9x16")
    values = {f"cell-{r}-{c}": str(r * 100 + c) for r in (1, 2, 3) for c in range(1, 7)}
    # Five periods on a phone since rebuild-41: the latest is the fifth, and
    # a sixth figure with no cell to hold it is not the one counted.
    assert MV._figure_slots(plate, values, "band-2") == ["cell-2-5"]
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


def test_a_push_in_never_lands_a_line_under_the_caption(vertical, reg, settings):
    """The caption is placed against the plate at rest, and the push carries
    the lines below the passage down the frame. On the 9:16 paper band the
    line under the headline landed under the caption and was read through it;
    such a passage gets the highlight instead."""
    fmt, result, words, _ = vertical
    plates = MV.shot_plates(result)
    captions = {l.shot_id: l for l in result.layers if l.kind == "caption"}
    for plan in _plans(fmt, result, words, reg, settings, n=12):
        for m in plan.moves:
            if m.move != "zoom-to-slot" or m.shot_id not in captions:
                continue
            layer, cap = plates[m.shot_id], captions[m.shot_id]
            plate = reg.get(layer.entry_key)
            box = MV._ink_box(plate, m.slot, layer.values[m.slot], settings, reg)
            vx, vy, vw, vh = M.zoom_box(plate.canvas, box, 1.0, MV.zoom_pad(
                plate.canvas, box, MV._zoom_pad_of(plate)))
            vw, vh = min(vw, plate.canvas[0]), min(vh, plate.canvas[1])
            vx = min(max(vx, 0.0), plate.canvas[0] - vw)
            vy = min(max(vy, 0.0), plate.canvas[1] - vh)
            for name, text in layer.values.items():
                slot = plate.slot(name)
                if slot is None or slot.region or slot.control or not str(text).strip():
                    continue
                ink = MV._ink_box(plate, name, str(text), settings, reg)
                if ink is None:
                    continue
                y0 = layer.y + (ink.y - vy) * layer.h / vh
                y1 = y0 + ink.h * layer.h / vh
                x0 = layer.x + (ink.x - vx) * layer.w / vw
                x1 = x0 + ink.w * layer.w / vw
                assert not (x0 < cap.x + cap.w and x1 > cap.x
                            and y0 < cap.y + cap.h and y1 > cap.y), \
                    (m.shot_id, plate.key, name, (round(y0), round(y1)),
                     (cap.y, cap.y + cap.h))


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
        # A numbers card (`numbers-3`) is a step of the numbers beat.
        assert all(re.sub(r"-\d+$", "", m.shot_id) in MV.CIRCLE_SHOTS
                   or m.shot_id in MV.CIRCLE_SHOTS for m in rings)
    rate = sum(any(m.move == "pen-circle" for m in p.moves) for p in plans) / len(plans)
    assert rate <= 0.5, f"the circle played in {rate:.0%} of sixty shorts"


def test_the_circle_never_rings_a_figure_that_fills_its_plate(reg, settings):
    """big-number sets its figure across the frame: a ring round it is a ring
    round the plate. A cell on a full sheet is what the pen is for."""
    big = reg.get("figures/big-number-l2-9x16")
    # A figure as long as its budget spans the plate (rebuild-41 sets the
    # slot so one does); a shorter one is a smaller part of it.
    assert MV.circle_box(big, "value", "-$496M", settings, reg) is None
    sheet = reg.get("tables/numbers-sheet-4r-9x16")
    box = MV.circle_box(sheet, "cell-1-5", "496", settings, reg)
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


def test_on_the_numbers_the_circle_rings_the_figure_the_payoff_says(short, reg, settings):
    """One card a row (item 26): the ring goes on the card of the row the
    verdict names, round the figure the payoff is about to say."""
    fmt, result, words, _ = short
    plates = MV.shot_plates(result)
    payoff = plates["payoff"]
    rang = 0
    for plan in _plans(fmt, result, words, reg, settings, n=60):
        for m in plan.moves:
            if m.move == "pen-circle" and m.shot_id.startswith("numbers"):
                rang += 1
                assert MV.figure_number(plates[m.shot_id].values[m.slot]) == \
                    MV.figure_number(payoff.values.get("value")
                                     or payoff.values.get("num"))
    assert rang, "the pen never found the verdict's figure on its card"


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
    marked = ("the-news", "numbers", "the-comment", "payoff")
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
            assert m.start >= wipe.end - 1e-9


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

    from pipeline.reach import recent_moves

    s = settings.model_copy(update={"workspace_dir": tmp_path})
    a = tmp_path / "EXMPL" / "2026-09-25"
    b = tmp_path / "OTHER" / "2026-09-26"
    for ws, moves in ((a, ["pen-circle", "count-up"]), (b, ["count-up"])):
        ws.mkdir(parents=True)
        (ws / "short_final.manifest.json").write_text(json.dumps(
            {"moves": {"moves": [{"move": m, "start": 1.0} for m in moves]}}),
            encoding="utf-8")
    import os
    os.utime(a / "short_final.manifest.json", (1, 1))
    assert recent_moves(s, window=1) == {"count-up"}
    assert recent_moves(s, window=1, exclude=b) == {"pen-circle", "count-up"}
    assert MV.recent_circled(s, exclude=b) is True
    assert MV.recent_circled(s) is False
    (tmp_path / "old" / "x").mkdir(parents=True)
    (tmp_path / "old" / "x" / "a.manifest.json").write_text("{}", encoding="utf-8")
    assert "pen-circle" in recent_moves(s, window=3)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _layer(result, shot_id):
    return MV.shot_plates(result)[shot_id]


def _sheet_layer(script, t_start: float = 10.0):
    """A full numbers sheet, as the long and the old short set one.

    No vertical template draws a sheet any more (item 26), but the band
    sweep and the ring are the compositor's, and a sheet is the plate that
    has both a band per row and small figures to ring.
    """
    from pipeline.compose import Layer

    # The five latest periods: a phone's sheet has five columns (rebuild-41).
    values = {f"head-{i + 1}": y for i, y in enumerate(script.years[:6][-5:])}
    for r, row in enumerate(script.numbers[:4], start=1):
        values[f"label-{r}"] = row.label
        for c, v in enumerate(row.values[:6][-5:], start=1):
            values[f"cell-{r}-{c}"] = v
    key = "tables/numbers-sheet-4r-9x16"
    return Layer(name=f"numbers:plate:{key}", kind="plate", shot_id="numbers",
                 t_start=t_start, t_end=t_start + 8.0, x=0, y=0, w=1080, h=1920,
                 entry_key=key, values=values)


def _diff(a, b) -> float:
    import numpy as np

    x = np.asarray(a.convert("RGBA"), dtype=np.int16)
    y = np.asarray(b.convert("RGBA"), dtype=np.int16)
    return float(np.abs(x - y).mean())


def test_a_landed_count_up_leaves_the_plate_as_its_still(short, reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    fmt, result, words, _ = short
    # The first plate holding one figure in `value`: which drawing a beat gets
    # rotates (the move beat may draw the session's chart instead).
    shot_id, layer = next((k, l) for k, l in MV.shot_plates(result).items()
                          if MV.is_one_figure(l.values.get("value", "")))
    move = MV.Move("count-up", shot_id, layer.name, "value", layer.t_start, 7,
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

    fmt, result, words, script = short
    layer = _sheet_layer(script)
    move = MV.Move("highlight", "numbers", layer.name, "band-1", layer.t_start, 6, "out")
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
    # Landed, the row is lit: the sheet drawn with that band up.
    still = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    still.alpha_composite(cache.plate(layer.entry_key, 0, {**layer.values, "band-1": "1"},
                                      layer.w, layer.h),
                          (layer.x, layer.y))
    box = (int(layer.x + band.x * k), int(layer.y + band.y * k),
           int(layer.x + (band.x + band.w) * k), int(layer.y + (band.y + band.h) * k))
    diffs = [_diff(fr.crop(box), still.crop(box)) for fr in frames]
    assert diffs[0] > diffs[-1]
    assert diffs[-1] < 0.5
    # And a row lit as it is read stays lit for the rest of the shot.
    later = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_layer(later, layer, move.start + 2.0, 0)
    assert _diff(later.crop(box), still.crop(box)) < 0.5


def test_the_ring_is_drawn_round_the_figure_not_the_slot(short, reg, settings):
    from PIL import Image

    from pipeline.render_short import _Cache

    fmt, result, words, script = short
    layer = _sheet_layer(script)
    slot = "cell-1-5"
    move = MV.Move("pen-circle", "numbers", layer.name, slot, layer.t_start, 8, "inOut")
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


@pytest.mark.parametrize("text", [
    "Goodwill impairment of $1.2bn was recorded in the fourth quarter.",
    "Goodwill impairment of $1.2bn was recorded in the fourth quarter, after "
    "the segment missed its plan for a second year and the discount rate "
    "used in the test rose by two points."])
def test_the_underline_sits_under_the_line_the_copy_ends_on(reg, settings, text):
    """Design's highlight: under the anchor's line that the copy's last line
    sits in, not under a tall box a third of the frame below the words."""
    plate = reg.get("paper/footnote-spotlight-9x16")
    anchor = plate.motion["highlight"]
    line = MV.underline_line(plate, anchor["slot"], text, settings, reg)
    ink = MV._ink_box(plate, anchor["slot"], text, settings, reg)
    # One of design's lines where the copy ends in one; where the type sets
    # taller than design's leading (rebuild-41's 34 on a phone, and the long
    # copy shrunk to fit), the anchor's line moved under the ink.
    first = anchor["lines"][0]
    assert dict(line._asdict()) in anchor["lines"] or \
        (line.x, line.w, line.h) == (first["x"], first["w"], first["h"])
    assert line.y < ink.y + ink.h <= line.y + line.h + 8


@pytest.mark.parametrize("key, text", [
    ("shorts/hook-card-t5", "EXMPL is up 29% today. The business is not."),
    ("shorts/hook-card-t3", "EXMPL beat and raised. The five-year chart didn't notice."),
    ("paper/press-release-9x16",
     "Example Corp Announces AI Partnership with a Cloud Provider")])
def test_the_underline_never_runs_through_or_above_the_words(reg, settings, key, text):
    """A slot set in the middle of its box puts its last line away from the
    anchor's lines. The rule went through the hook's second line on one
    card and above its first on another (2 Oct 2026): it goes under the ink."""
    plate = reg.get(key)
    slot = plate.motion["highlight"]["slot"]
    line = MV.underline_line(plate, slot, text, settings, reg)
    ink = MV._ink_box(plate, slot, text, settings, reg)
    foot = ink.y + ink.h
    assert foot <= line.y + line.h <= foot + 8


@pytest.mark.parametrize("name, frames", [("wipe-sweep", 8), ("wipe-page", 8),
                                          ("wipe-blinds", 8),
                                          ("wipe-sweep-short", 4),
                                          ("wipe-page-short", 4),
                                          ("wipe-blinds-short", 4)])
def test_a_wipe_covers_the_whole_frame_on_the_cut(reg, settings, name, frames):
    """Design made the cut frame fully opaque (rebuild-40): the two shots are
    cut under it and neither shows through."""
    from PIL import Image

    from pipeline.render_short import _Cache

    key = reg.aspect_key(f"overlays/{name}", "9x16")
    plate = reg.get(key)
    spec = (plate.transition or {}) if plate is not None else {}
    assert spec.get("frames") == frames and spec.get("cutAt") == frames // 2
    w = MV.Wipe(key=key, cut=5.0, shot_out="a", shot_in="b", frames=frames,
                cut_frame=frames // 2 - 1)
    comp = MV.MoveCompositor(MV.MovePlan(wipes=[w]), reg, settings, _Cache(settings, reg))
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    comp.draw_overlays(img, w.cut + 0.01)
    import numpy as np

    alpha = np.asarray(img)[:, :, 3]
    assert (alpha == 255).mean() > 0.999, "the cut shows through the cover"


def test_a_short_wipes_in_design_s_four_frame_cuts(vertical, reg, settings):
    """The shorts are the fast lane: design's third-of-a-second wipes, the
    cut under the second frame, and the shot's moves wait only for those."""
    fmt, result, words, _ = vertical
    wipes = MV.plan_wipes(fmt, result, reg, seed="x")
    assert wipes
    for w in wipes:
        # At the hour that matches the cards' paper, so by its base key.
        assert reg.base_key(w.key).split("/")[1].rsplit("-", 1)[0].endswith("-short"), w.key
        assert (w.frames, w.cut_frame) == (4, 1)
        assert w.end - w.cut == pytest.approx(3 / 12)


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


# ---------------------------------------------------------------------------
# A column's figure comes up with its column
# ---------------------------------------------------------------------------

def test_no_column_figure_counts_up_on_its_own(short, reg, settings):
    """Valentin, 10 Oct 2026: on the revenue bars FY23 to FY25 showed their
    figures at once, then FY21, FY22 and LTM counted up one by one — only the
    slots a list of figure names happened to hold were counted. A column's
    figure now rides its column, so none gets a count-up of its own."""
    fmt, result, words, _ = short
    charts = [k for k, l in MV.shot_plates(result).items()
              if any(n.startswith(("bar-", "point-")) for n in reg.get(l.entry_key).slots)]
    assert charts, "the fixture short has no column chart"
    for plan in _plans(fmt, result, words, reg, settings, n=6):
        counted = [(m.shot_id, m.slot) for m in plan.moves
                   if m.move == "count-up" and m.shot_id in charts]
        assert not [c for c in counted if re.match(r"^value-\d+$", c[1])], counted


def test_bar_figures_rise_left_to_right_with_their_bars(reg, settings):
    plate = reg.get("charts/bars-6y-9x16")
    values = {f"value-{i}": f"${v}M" for i, v in enumerate((400, 431, 458, 472, 486, 496), 1)}
    move = MV.Move("bars-grow", "s", "l", "plot-area", 0.0, 13, "out")
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg, settings, None)
    assert all(k == 0.0 for k in comp._column_figures(plate, (move, None), values).values())
    for f in range(13):
        got = comp._column_figures(plate, (move, f), values)
        ks = [got[f"value-{i}"] for i in range(1, 7)]
        assert ks == sorted(ks, reverse=True), (f, ks)
    assert all(k == 1.0 for k in comp._column_figures(plate, (move, 12), values).values())


def test_no_bar_outline_stands_before_its_bar_grows(reg, settings):
    """On paper the bars' black outlines stood the full height of every empty
    column for the first second of a bars-grow: the sides of each bar sit on
    its column's edges, half outside the box the grow clipped to."""
    import numpy as np

    plate = reg.at("night").get("charts/bars-6y-9x16")
    values = {f"value-{i}": f"${v}M" for i, v in enumerate((400, 431, 458, 472, 486, 496), 1)}
    values.update({f"y-{i}": f"${v}M" for i, v in enumerate((0, 125, 250, 375, 500), 1)})
    move = MV.Move("bars-grow", "s", "l", "plot-area", 0.0, 13, "out")
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg.at("night"), settings, None)
    data = comp._data(plate, tuple(sorted(values.items())), "")
    assert data is not None
    hidden = np.asarray(comp._reveal(data, plate, move, None, values))[..., 3]
    k = plate.export_scale
    for c in MV._columns(plate):
        b = c["box"]
        x0, x1 = int((b["x"] - 3) * k), int((b["x"] + b["w"] + 3) * k)
        y0, y1 = int(b["y"] * k), int((b["y"] + b["h"] - 4) * k)
        assert not hidden[y0:y1, x0:x1].any(), c["slots"]


def test_line_figures_wait_for_the_line_to_reach_their_point(reg, settings):
    plate = reg.get("charts/line-6y-16x9")
    move = MV.Move("line-draw", "s", "l", "plot-area", 0.0, 10, "linear")
    comp = MV.MoveCompositor(MV.MovePlan(moves=[move]), reg, settings, None)
    seen = []
    for f in range(10):
        got = comp._column_figures(plate, (move, f), {})
        seen.append(sum(got.values()))
    assert seen == sorted(seen) and seen[0] < 6 and seen[-1] == 6


@pytest.mark.parametrize("hour", ["night", "dusk"])
def test_a_wipe_between_paper_cards_is_paper_at_every_hour(reg, hour):
    """10 Oct 2026: the night's navy sweep between two paper cards flashed the
    frame dark for half a second, the flip the all-paper plates were for."""
    from pipeline.moves import wipe_for_ground, wipe_plate
    from pipeline.plate_frames import _rgb

    at = reg.at(hour)
    card = at.get(at.aspect_key("cards/quote-pull", "9x16"))
    assert card.ground == "paper"
    for name in ("wipe-sweep", "wipe-page"):
        wipe = wipe_for_ground(at, wipe_plate(at, name, "9x16"), card)
        ground = _rgb(at.inks(wipe)["ground"])
        assert sum(ground) / 3 > 180, (hour, wipe.key, ground)
        # And the frame drawn at the cut is that hour's art, not the
        # episode's: asked for by key, a night view answered navy.
        from PIL import Image

        drawn = at.plate_at(wipe.key, wipe.hour)
        cover = Image.open(drawn.frame_paths()[1]).convert("RGB")
        px = cover.getpixel((cover.width // 4, cover.height // 2))
        assert sum(px) / 3 > 180, (hour, wipe.key, px)
    # A cut into the room keeps the episode's hour.
    w = wipe_plate(at, "wipe-sweep", "9x16")
    assert wipe_for_ground(at, w, None) is w


def test_the_short_draws_its_paper_wipe_at_night(short, reg, settings):
    """The plan names the cream sweep and the frame on screen is the cream one."""
    fmt, result, words, _ = short
    night = reg.at("night")
    wipes = MV.plan_wipes(fmt, result, night, seed="x")
    assert wipes and all(w.hour == "dusk" for w in wipes), [(w.key, w.hour) for w in wipes]
    comp = MV.MoveCompositor.__new__(MV.MoveCompositor)
    comp.reg = night

    class Files:
        def file(self, path, w, h):
            from PIL import Image
            return Image.open(path).convert("RGBA").resize((w, h))

        def plate(self, *a):
            raise AssertionError("asked for by key, at the episode's hour")

    comp.cache = Files()
    w = wipes[0]
    img = comp._wipe_frame(w, w.cut_frame, 108, 192).convert("RGB")
    assert sum(img.getpixel((27, 96))) / 3 > 180
