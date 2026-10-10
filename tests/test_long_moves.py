"""The LONG's moves: the writer's [MOVE]s and the data drawing on, beat by beat."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pipeline import moves as MV
from pipeline import render_long as RL


@pytest.fixture(scope="module")
def settings():
    from config import Settings
    return Settings(MOCK_MODE=True, _env_file=None)


@pytest.fixture(scope="module")
def reg(settings):
    from pipeline.plates import load_plates
    return load_plates(settings.assets_dir)


YEARS = ["FY20", "FY21", "FY22", "FY23", "FY24", "FY25"]
BARS = ("charts/bars-6y-16x9", {
    **{f"head-{i}": y for i, y in enumerate(YEARS, start=1)},
    **{f"value-{i}": v for i, v in enumerate(["1.2", "1.5", "1.9", "2.4", "2.2", "3.1"],
                                             start=1)},
    "unit": "$bn"})
CALLOUT = ("charts/earnings-vs-cash-16x9", {"kicker": "EARNINGS VS CASH", "gap": "$1.2bn"})


def _row(move, slot, at, text, order=0):
    return {"move": move, "slot": slot, "at": at, "text": text, "order": order}


def _plan(reg, settings, case, rows=(), *, seg_len=6.0, earliest=0.0):
    key, values = case
    return MV.plan_segment(reg.get(key), values, list(rows), seg_len=seg_len,
                           shot_id="segment_4", layer="segment_4", earliest=earliest,
                           settings=settings, reg=reg)


def test_a_chart_s_data_draws_on_as_the_beat_is_first_seen(reg, settings):
    moves, skipped = _plan(reg, settings, BARS, earliest=2.0)
    assert [m.move for m in moves] == ["bars-grow"] and skipped == []
    assert moves[0].start == pytest.approx(2.0)
    # Column by column, each a frame after the one before: design's eight
    # frames plus one for each of the five columns after the first.
    assert moves[0].frames == 8 + 6 - 1


def test_bars_grow_one_column_at_a_time_inside_their_own_columns(reg, settings):
    """Frame f shows column i grown to out(stagger(f, i)), clipped to that
    column's box; nothing outside the columns is part of the move."""
    from PIL import Image

    from pipeline import motion as M

    key, values = BARS
    plate = reg.get(key)
    moves, _ = _plan(reg, settings, BARS)
    comp = MV.MoveCompositor(MV.MovePlan(moves=moves), reg, settings, None)
    s = plate.export_scale
    full = Image.new("RGBA", plate.pixel_size, (255, 0, 0, 255))
    cols = plate.motion["bars-grow"]["columns"]
    for f in (0, 3, 12):
        got = np.asarray(comp._reveal(full, plate, moves[0], f, values=values))[..., 3]
        for i, c in enumerate(cols):
            b = c["box"]
            shown = M.reveal(M.Box(b["x"], b["y"], b["w"], b["h"]),
                             M.out(M.stagger(f, i, 8)), "bottom")
            col = got[int(b["y"] * s):int((b["y"] + b["h"]) * s),
                      int((b["x"] + 2) * s):int((b["x"] + b["w"] - 2) * s)]
            want = shown.h / b["h"]
            assert abs((col > 0).mean() - want) < 0.02, (f, i)
        # Between the columns the layer is never cut (past the bar's own
        # outline, which goes in with its column).
        gap = cols[0]["box"]["x"] + cols[0]["box"]["w"] + MV.BAR_STROKE_BLEED + 4
        assert got[int(400 * s), int(gap * s)] == 255


def test_the_writer_s_moves_play_on_their_words_one_after_another(reg, settings):
    moves, skipped = _plan(reg, settings, CALLOUT, [
        _row("count-up", "gap", 1.0, "$1.2bn"),
        _row("pen-circle", "gap", 1.1, "$1.2bn", order=1)])
    assert [m.move for m in moves] == ["count-up", "pen-circle"], skipped
    assert moves[0].start == pytest.approx(1.0)
    assert moves[1].start >= moves[0].end + MV.MOVE_GAP_S - 1e-9
    assert all(m.end <= 6.0 - MV.END_MARGIN_S + 1e-9 for m in moves)
    assert {m.shot_id for m in moves} == {"segment_4"}


def test_a_move_that_cannot_land_before_the_cut_is_not_started(reg, settings):
    moves, skipped = _plan(reg, settings, CALLOUT, [_row("count-up", "gap", 5.8, "$1.2bn")])
    assert moves == []
    assert "before the beat cuts" in skipped[0]


def test_the_long_never_rings_a_figure_that_fills_its_plate(reg, settings):
    big = ("figures/big-number-l1-16x9", {"kicker": "FREE CASH FLOW", "value": "$3.1bn"})
    moves, skipped = _plan(reg, settings, big, [_row("pen-circle", "value", 1.0, "$3.1bn")])
    assert moves == []
    assert "without ringing the plate" in skipped[0]


def test_a_count_up_needs_one_figure_to_count_to(reg, settings):
    moves, skipped = _plan(reg, settings, CALLOUT,
                           [_row("count-up", "gap", 1.0, "$1.2bn to $1.4bn")])
    assert moves == [] and "not one figure" in skipped[0]


def test_the_beat_s_clip_draws_every_video_frame_and_ends_landed(reg, settings, tmp_path,
                                                               monkeypatch):
    got: dict = {}

    def held(frames, out, *, fps=12):
        got["held"], got["fps"] = frames, fps
        return out

    def loop(frames, fps, out):
        got["loop"] = (frames, fps)
        return out

    monkeypatch.setattr("pipeline.rasters.held_frames_to_alpha_clip", held)
    monkeypatch.setattr("pipeline.rasters.frames_to_alpha_clip", loop)
    key, values = BARS
    plate = reg.get(key)
    moves, _ = _plan(reg, settings, BARS, earliest=0.5)
    clips = MV.render_segment(plate, values, moves, seg_len=6.0, size=(480, 270),
                              settings=settings, reg=reg, out_dir=tmp_path, stem="p")
    # Drawn at design's 12 fps, played at the video's: every frame of the
    # move is a new drawing, not a 12 fps step held for two or three frames.
    assert got["fps"] == MV.OUT_FPS
    secs = [s for _, s in got["held"]]
    # Every hold is a whole number of the video's frames, and the clip runs
    # until the last move has landed.
    assert all(abs(s * MV.OUT_FPS - round(s * MV.OUT_FPS)) < 1e-6 for s in secs)
    landed = max(m.end for m in moves)
    assert sum(secs) >= landed - 1e-6
    assert clips.landed_at == pytest.approx(sum(secs) - 1 / MV.OUT_FPS)
    # A boiling chart goes on boiling once the bars are up: its loop is the
    # plate's own boil, and the clip's last frame is one of its frames.
    frames, fps = got["loop"]
    assert len(frames) == plate.frame_count and fps == max(int(plate.fps or 2), 1)
    last = np.asarray(got["held"][-1][0], dtype=np.int16)
    b = int(math.floor(clips.landed_at * fps + 1e-9)) % len(frames)
    assert np.abs(last - np.asarray(frames[b], dtype=np.int16)).max() == 0
    # And before the bars grow, the plot is empty where they end up.
    first = np.asarray(got["held"][0][0], dtype=np.int16)
    assert np.abs(first - last).mean() > 1.0


def test_a_beat_with_no_moves_draws_no_clip(reg, settings, tmp_path):
    key, values = CALLOUT
    assert MV.render_segment(reg.get(key), values, [], seg_len=6.0, size=(480, 270),
                             settings=settings, reg=reg, out_dir=tmp_path,
                             stem="p") is None


def test_a_beat_under_a_cover_waits_for_it_to_lift():
    bumper = [(9.75, 12.0)]
    assert RL._cleared(10.0, bumper) == 12.0
    assert RL._cleared(12.5, bumper) == 12.5
    # Covers that overlap lift together: the title, then the wipe off it.
    assert RL._cleared(0.0, [(2.35, 2.93), (0.0, 2.6)]) == pytest.approx(2.93)


def test_each_chapter_lands_on_its_own_cut():
    chapters = [(1.0, "a", "x"), (6.0, "b", "y"), (6.5, "c", "z"), (40.0, "d", "w")]
    starts = [0.0, 2.0, 7.0, 9.0, 12.0]
    assert RL._chapter_cuts(chapters, starts, intro_dur=0.5, duration=30.0) == \
        [2.0, 7.0, 9.0, None]


def test_a_first_chapter_under_the_opening_title_has_no_second_opener():
    """The title card is chapter one's opener: its headline is the chapter's
    title. Landed on the first cut after the card as well, it was the empty
    room with the same title in it, five seconds in, and he vanished."""
    chapters = [(0.0, "a", "x"), (6.0, "b", "y"), (6.5, "c", "z")]
    starts = [0.0, 2.0, 5.0, 7.0, 9.0]
    assert RL._chapter_cuts(chapters, starts, intro_dur=2.6, duration=30.0) == \
        [None, 7.0, 9.0]


# ---------------------------------------------------------------------------
# Through the real render
# ---------------------------------------------------------------------------

MOVES_RAW = """EXMPL made money on paper and not in the bank, and that is the whole story today.
Here is the gap. [PLATE: earnings-vs-cash-16x9 | kicker=EARNINGS VS CASH | gap=$1.2bn] [SOURCE: FY25 10-K, cash flow statement] Earnings ran ahead of cash by [MOVE: count-up] one point two billion dollars, and that is the number to remember for the rest of this.
Then the revenue, six years of it. [PLATE: bars-6y-16x9 | head-1=FY20 | head-2=FY21 | head-3=FY22 | head-4=FY23 | head-5=FY24 | head-6=FY25 | value-1=1.2 | value-2=1.5 | value-3=1.9 | value-4=2.4 | value-5=2.2 | value-6=3.1 | unit=$bn] It grew in five of those six years, which is the good news, and it is most of the good news.
That is where it stands for now. See you at the next filing.

=== CHAPTERS ===
00:00 cold-open | paper and not the bank
00:08 the-numbers | where the gap is"""


@pytest.fixture(scope="module")
def rendered_moves(tmp_path_factory):
    from config import Settings
    from pipeline.broll import ContentManager
    from pipeline.parser_long import parse_long_script
    from pipeline.render_long import render_long
    from pipeline.tts import TTSEngine

    tmp = tmp_path_factory.mktemp("long_moves")
    settings = Settings(MOCK_MODE=True, workspace_dir=tmp / "ws", cache_dir=tmp / "cache",
                        state_dir=tmp / "state", long_width=640, long_height=360,
                        long_min_chars=0, _env_file=None)
    settings.ensure_runtime_dirs()
    script, _ = parse_long_script(MOVES_RAW, "EXMPL", settings)
    ws = settings.workspace_dir / "EXMPL" / "moves"
    ws.mkdir(parents=True)
    tts = TTSEngine(settings).synthesize(script.narration, "long")
    out, manifest = render_long(script, tts, ws, settings,
                                content=ContentManager(settings), as_of="2026-07-01")
    import json
    return out, json.loads(manifest.read_text(encoding="utf-8"))


def test_the_writer_s_count_up_and_the_bars_play_in_the_cut(rendered_moves):
    out, manifest = rendered_moves
    assert out.exists() and out.stat().st_size > 0
    rows = manifest["moves"]["moves"]
    plates = {i: s for i, s in enumerate(manifest["segments"]) if s["kind"] == "plate"}
    played = {r["move"]: r for r in rows if r["shot_id"].startswith("segment_")}
    assert set(played) >= {"count-up", "bars-grow"}, (rows, manifest["moves"]["skipped"])
    for r in played.values():
        seg = plates[int(r["shot_id"].split("_")[1])]
        assert seg["start"] <= r["start"] < seg["end"]
    count = played["count-up"]
    assert count["slot"] == "gap"
    # On the word it was written on, or when the chapter bumper over that
    # word lifts: a move under a full-frame cover is a move nobody sees.
    wm = next(m for m in manifest["writer_moves"] if m["move"] == "count-up")
    covers = [(l["t_start"], l["t_end"]) for l in manifest["layers"]
              if l["name"].startswith("chapter_") or l["name"] == "intro_card"]
    under = [b for a, b in covers if a <= wm["t"] < b]
    want = max(under) if under else wm["t"]
    assert count["start"] == pytest.approx(want, abs=1 / 12)
    assert not any(a <= count["start"] < b - 1e-3 for a, b in covers)


def test_the_source_slides_in_once_the_figure_has_counted_up(rendered_moves):
    _, manifest = rendered_moves
    (src,) = manifest["sources"]
    assert src["text"] == "FY25 10-K, cash flow statement"
    shot = f"segment_{src['segment']}"
    rows = manifest["moves"]["moves"]
    count = next(r for r in rows if r["move"] == "count-up" and r["shot_id"] == shot)
    slide = next(r for r in rows if r["move"] == "slide-in" and r["shot_id"] == shot)
    # After the figure has landed (7 frames) and held to the end of the beat.
    assert slide["start"] >= count["start"] + 7 / 12
    assert slide["start"] == pytest.approx(src["start"])
    seg = manifest["segments"][src["segment"]]
    assert src["end"] == pytest.approx(seg["end"], abs=1e-3)
    layer = next(l for l in manifest["layers"] if l["name"] == f"source_{src['segment']}")
    assert layer["t_start"] == pytest.approx(src["start"], abs=1e-3)


# ------------------------------------------- the plate builds as he talks (57)
def _words(*timed):
    from types import SimpleNamespace

    out = []
    for at, text in timed:
        for k, w in enumerate(text.split()):
            out.append(SimpleNamespace(word=w, start=at + 0.25 * k, end=at + 0.25 * k + 0.2))
    return out


SHEET = ("tables/numbers-sheet-4r-16x9", {
    **{f"head-{i}": y for i, y in enumerate(YEARS, start=1)},
    "label-1": "Revenue", "label-2": "Gross margin", "label-3": "Free cash flow",
    "label-4": "Share count",
    **{f"cell-1-{i}": v for i, v in enumerate(["400M", "452M", "471M", "491M", "496M", "496M"], 1)},
    **{f"cell-2-{i}": v for i, v in enumerate(["52%", "55%", "56%", "58%", "58%", "57%"], 1)},
    **{f"cell-3-{i}": v for i, v in enumerate(["-12M", "4M", "9M", "-30M", "-71M", "-60M"], 1)},
    **{f"cell-4-{i}": v for i, v in enumerate(["88M", "90M", "93M", "97M", "101M", "104M"], 1)},
    "unit": "USD"})


def test_a_sheet_s_rows_go_on_as_he_names_them(reg, settings):
    key, values = SHEET
    words = _words((100.0, "the business sells more every year"),
                   (101.5, "gross margin held up"),
                   (103.0, "but the share count keeps climbing"))
    moves, _ = MV.plan_segment(reg.get(key), values, [], seg_len=7.0, shot_id="s",
                               layer="s", settings=settings, reg=reg, words=words,
                               at=100.0)
    rows = [(m.slot, round(m.start, 2)) for m in moves if m.move == "row-on"]
    # The first row comes with the sheet; row 2 on "gross margin"; row 3 is
    # never said and comes with row 2; row 4 on "share count".
    assert rows == [("band-2", 1.5), ("band-3", 1.5), ("band-4", 3.5)]
    # Pushed into from his monitor, it was already whole: nothing builds.
    drawn, _ = MV.plan_segment(reg.get(key), values, [], seg_len=7.0, shot_id="s",
                               layer="s", settings=settings, reg=reg, words=words,
                               at=100.0, drawn=True)
    assert not [m for m in drawn if m.move in MV.BUILD_MOVES]


def test_a_row_is_off_the_sheet_until_its_word(reg, settings):
    key, values = SHEET
    plate = reg.get(key)
    rows = dict(MV.build_rows(plate, values))
    assert list(rows) == ["band-1", "band-2", "band-3", "band-4"]
    assert {"label-4", "cell-4-6", "band-4"} <= rows["band-4"]
    assert not any(n.startswith("head-") for s in rows.values() for n in s)
    mv = MV.Move("row-on", "s", "s", "band-4", 1.0, 1)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[mv]), reg, settings, None)
    from types import SimpleNamespace

    layer = SimpleNamespace(kind="plate", name="s", entry_key=key, values=values,
                            x=0, y=0, w=1920, h=1080, seed="")
    before = np.asarray(comp.frame(layer, 0.5, 0)).astype(int)
    after = np.asarray(comp.frame(layer, 1.2, 0)).astype(int)
    s = before.shape[1] / plate.canvas[0]
    lab = plate.slots["label-4"]
    box = (slice(int(lab.y * s), int((lab.y + lab.h) * s)),
           slice(int(lab.x * s), int((lab.x + lab.w) * s)))
    assert np.abs(before[box] - after[box]).sum() > 0, "row 4 was on before its word"
    top = plate.slots["label-1"]
    box1 = (slice(int(top.y * s), int((top.y + top.h) * s)),
            slice(int(top.x * s), int((top.x + top.w) * s)))
    assert (before[box1] == after[box1]).all(), "row 1 changed"


def test_a_row_not_yet_said_leaves_no_bullet(reg, settings):
    """The ladder draws a bullet in each step's band; a step he has not named
    yet shows none of it, only the plate's ground."""
    key = "structure/unit-ladder-16x9"
    plate = reg.get(key)
    values = {"top-label": "Revenue", "top-value": "496",
              **{f"step-{i}-label": f"Cost {i}" for i in range(1, 6)},
              **{f"step-{i}-value": f"-{i}0" for i in range(1, 6)}}
    from types import SimpleNamespace

    layer = SimpleNamespace(kind="plate", name="s", entry_key=key, values=values,
                            x=0, y=0, w=1920, h=1080, seed="")
    mv = MV.Move("row-on", "s", "s", "band-3", 1.0, 1)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[mv]), reg, settings, None)
    before = np.asarray(comp.frame(layer, 0.5, 0).convert("RGB")).astype(int)
    k = before.shape[1] / plate.canvas[0]
    b = plate.slots["band-3"]
    inside = before[int(b.y * k) + 2:int((b.y + b.h) * k) - 2,
                    int(b.x * k) + 2:int((b.x + b.w) * k) - 2]
    assert np.ptp(inside.reshape(-1, 3), axis=0).max() <= 2, "the unsaid row left marks"
    after = np.asarray(comp.frame(layer, 1.2, 0).convert("RGB")).astype(int)
    shown = after[int(b.y * k) + 2:int((b.y + b.h) * k) - 2,
                  int(b.x * k) + 2:int((b.x + b.w) * k) - 2]
    assert np.ptp(shown.reshape(-1, 3), axis=0).max() > 40, "the row never came on"


def test_a_row_not_yet_said_keeps_the_sheet(reg, settings):
    """A numbers sheet's column rules and zebra run through every row: they
    are the sheet, so an unsaid row keeps them and only its type waits."""
    key = "tables/numbers-sheet-4r-16x9"
    plate = reg.get(key)
    values = {n: "12.4" for n, sl in plate.slots.items() if sl.is_text}
    from types import SimpleNamespace

    layer = SimpleNamespace(kind="plate", name="s", entry_key=key, values=values,
                            x=0, y=0, w=1920, h=1080, seed="")
    mv = MV.Move("row-on", "s", "s", "band-3", 1.0, 1)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[mv]), reg, settings, None)
    before = np.asarray(comp.frame(layer, 0.5, 0).convert("RGB")).astype(int)
    from pipeline.plate_frames import render_frame

    bare = np.asarray(render_frame(plate, 0, {}, settings, reg).convert("RGB")
                      .resize((before.shape[1], before.shape[0]))).astype(int)
    k = before.shape[1] / plate.canvas[0]
    b = plate.slots["band-3"]
    box = (slice(int(b.y * k), int((b.y + b.h) * k)), slice(int(b.x * k), int((b.x + b.w) * k)))
    assert np.abs(before[box] - bare[box]).max() <= 8, "the unsaid row lost the sheet's lines"


def test_a_boxed_row_not_yet_said_is_not_an_empty_box(reg, settings):
    """The sheet boxes its alternate rows in the art. With the row not yet
    said, the box stood empty on the plate, an outlined field waiting for
    something; until its word the row is the sheet's plain ground, column
    rules and all, and the box comes on with the row."""
    key = "tables/numbers-sheet-4r-16x9"
    plate = reg.get(key)
    values = {n: "12.4" for n, sl in plate.slots.items() if sl.is_text}
    from types import SimpleNamespace

    layer = SimpleNamespace(kind="plate", name="s", entry_key=key, values=values,
                            x=0, y=0, w=1920, h=1080, seed="")
    mv = MV.Move("row-on", "s", "s", "band-2", 1.0, 1)
    comp = MV.MoveCompositor(MV.MovePlan(moves=[mv]), reg, settings, None)
    before = np.asarray(comp.frame(layer, 0.5, 0).convert("RGB")).astype(int)
    after = np.asarray(comp.frame(layer, 1.2, 0).convert("RGB")).astype(int)
    k = before.shape[1] / plate.canvas[0]
    plain, boxed = plate.slots["band-3"], plate.slots["band-2"]

    def band(img, b):
        return img[int(b.y * k):int((b.y + b.h) * k), int(b.x * k):int((b.x + b.w) * k)]

    # unsaid, row 2 looks like the plain row below it, rules included
    assert np.abs(np.median(band(before, boxed).reshape(-1, 3), axis=0)
                  - np.median(band(before, plain).reshape(-1, 3), axis=0)).max() <= 3
    rules = lambda img, b: (np.abs(band(img, b) - np.median(band(img, b).reshape(-1, 3), axis=0))
                            .max(axis=2) > 12).mean(axis=0) > 0.6   # noqa: E731
    assert rules(before, boxed).sum() >= 6, "the column rules stopped at the row"
    # said, the box is back
    assert np.abs(np.median(band(after, boxed).reshape(-1, 3), axis=0)
                  - np.median(band(after, plain).reshape(-1, 3), axis=0)).max() > 6


def test_a_card_s_figure_goes_on_with_its_word(reg, settings):
    key = "figures/big-number-l1-16x9"
    values = {"kicker": "GROSS MARGIN", "value": "58%", "label": "on the LTM"}
    words = _words((50.0, "and the margin is fifty-eight percent today"))
    moves, _ = MV.plan_segment(reg.get(key), values, [], seg_len=6.0, shot_id="s",
                               layer="s", settings=settings, reg=reg, words=words,
                               at=50.0)
    assert [(m.move, m.slot, round(m.start, 2)) for m in moves] == [("figure-on", "value", 1.0)]
    # The writer's count-up on it is the writer's.
    called, _ = MV.plan_segment(reg.get(key), values,
                                [_row("count-up", "value", 1.0, "58%")], seg_len=6.0,
                                shot_id="s", layer="s", settings=settings, reg=reg,
                                words=words, at=50.0)
    assert [m.move for m in called] == ["count-up"]
    # Said too late into the beat, it is on from the start.
    late = _words((50.0, "a lot of words before we get to it at last"),
                  (54.5, "fifty-eight percent"))
    moves, _ = MV.plan_segment(reg.get(key), values, [], seg_len=6.0, shot_id="s",
                               layer="s", settings=settings, reg=reg, words=late, at=50.0)
    assert moves == []


def test_a_ladder_s_steps_go_on_by_their_label(reg, settings):
    key = "structure/unit-ladder-16x9"
    values = {"kicker": "FY25, $M", "top-label": "Revenue", "top-value": "496",
              **{f"step-{i}-label": l for i, l in enumerate(
                  ["Cost of revenue", "Sales and marketing", "R&D", "G&A", "Other"], 1)},
              **{f"step-{i}-value": v for i, v in enumerate(
                  ["-208", "-212", "-80", "-40", "-16"], 1)},
              "out-label": "Operating income", "out-value": "-60"}
    words = _words((159.4, "hundred and twelve million on sales and marketing to add five"))
    moves, _ = MV.plan_segment(reg.get(key), values, [], seg_len=8.0, shot_id="s",
                               layer="s", settings=settings, reg=reg, words=words,
                               at=159.4)
    rows = [(m.slot, round(m.start, 2)) for m in moves if m.move == "row-on"]
    # Step 2 on "sales and marketing"; steps 3 to 5, never said, with it.
    assert rows == [("band-2", 1.25), ("band-3", 1.25), ("band-4", 1.25), ("band-5", 1.25)]
