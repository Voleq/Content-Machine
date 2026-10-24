"""The episode written in the 3D room: the board and the monitor (item 36)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pipeline import room_dressing as rd
from pipeline.plates import Frame, Plate

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"

PAPER = (238, 241, 242)
BACKLIGHT = (148, 158, 170)
CLOSES = tuple(10 + i % 7 + i / 40 for i in range(300))
APP = (18, 28, 42)
_CHART_QUAD = [[105 + 90 * x / 1920, 5 + 90 * y / 1080]
               for x, y in ((60, 116), (1392, 116), (1392, 1044), (60, 1044))]


def _dressing(**kw) -> rd.Dressing:
    return rd.Dressing(**{"episode": 7, "ticker": "EXMPL",
                          "question": "who pays for the buyback?",
                          "chapters": ("The setup", "The cash", "The catch"),
                          "closes": CLOSES, **kw})


def _lin(c):
    c = np.asarray(c, dtype=np.float64) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def test_the_board_is_ink_on_a_clear_layer():
    img = rd.board_ink(_dressing(), FONTS, (900, 600))
    assert img.mode == "RGBA" and img.size == (900, 600)
    a = np.asarray(img)[..., 3]
    assert 0.02 < (a > 0).mean() < 0.5, "the board is blank or painted over"
    red = np.asarray(img)[..., :3][a > 0]
    assert ((red[:, 0] > 150) & (red[:, 1] < 60)).any(), "no red line for the price's run"


def test_no_price_line_without_a_real_series():
    with_line = np.asarray(rd.board_ink(_dressing(), FONTS, (900, 600)))
    without = np.asarray(rd.board_ink(_dressing(closes=()), FONTS, (900, 600)))
    red = lambda im: ((im[..., 0] > 150) & (im[..., 1] < 60) & (im[..., 3] > 0)).sum()  # noqa: E731
    assert red(with_line) > 0 and red(without) == 0
    chart = np.asarray(rd.screen_chart(_dressing(closes=()), FONTS, (640, 450)))
    assert not ((chart[..., 2] > 120) & (chart[..., 0] < 80)).any(), \
        "the monitor drew a line with no series"


def test_a_long_episode_question_still_fits_the_board():
    img = rd.board_ink(_dressing(question="x" * 40 + " what is this company worth"),
                       FONTS, (900, 600))
    a = np.asarray(img)[..., 3]
    assert a[:, -2:].max() == 0, "the writing ran off the board"


def test_the_warp_lands_on_its_corners():
    tex = Image.new("RGB", (100, 50), (255, 255, 255))
    quad = [(40.0, 30.0), (160.0, 40.0), (150.0, 100.0), (50.0, 90.0)]
    px, (x0, y0) = rd._warp(tex, quad, (200, 150))
    a = px[..., 3]
    assert a[60 - y0, 100 - x0] > 0.99, "the middle of the quad is not covered"
    assert a[0, 0] == 0 and a[-1, -1] == 0, "the warp painted outside its quad"


def _plate(tmp: Path, *, frames=("r.png", "r.png", "r_f03.png"), front=True) -> Plate:
    """A two-state room 200x100 canvas, delivered at 400x200, board on the
    left and screen on the right."""
    fam = tmp / "room"
    fam.mkdir(parents=True)
    paper = np.zeros((200, 400, 3), np.uint8)
    paper[:, :200] = PAPER
    paper[:, 200:] = BACKLIGHT
    Image.fromarray(paper).save(fam / "r.png")
    dim = (_lin(paper) * 0.55)
    dim8 = np.where(dim <= 0.0031308, dim * 12.92, 1.055 * dim ** (1 / 2.4) - 0.055)
    Image.fromarray((dim8 * 255 + 0.5).astype(np.uint8)).save(fam / "r_f03.png")
    mask_b = np.zeros((200, 400), np.uint8)
    mask_b[:, :200] = 255
    mask_b[:, 90:110] = 0          # something stands in front of the board here
    Image.fromarray(mask_b).save(fam / "r_mask_board.png")
    # The made-up app the room is rendered with, round the chart area: a
    # dark sidebar on the glass, right of the backlight.
    paper[30:170, 352:384] = APP
    Image.fromarray(paper).save(fam / "r.png")
    mask_s = np.zeros((200, 400), np.uint8)
    mask_s[:, 200:] = 255
    mask_s[10:30, 210:240] = 0     # a sticky note on the glass
    Image.fromarray(mask_s).save(fam / "r_mask_screen.png")
    if front:
        fr = np.zeros((200, 400, 4), np.uint8)
        fr[150:, 250:350, :3] = BACKLIGHT
        fr[150:, 250:350, 3] = 255
        Image.fromarray(fr, "RGBA").save(fam / "r_front.png")
    writable = {
        "board": {"quad": [[5, 5], [95, 5], [95, 95], [5, 95]], "paper": list(PAPER),
                  "size": [1.4, 1.0], "mask": "r_mask_board.png"},
        # The chart area, placed where the room's texture puts it inside a
        # glass that is canvas x 105..195, y 5..95.
        "screen": {"quad": _CHART_QUAD,
                   "backlight": list(BACKLIGHT), "size": [1332, 928],
                   "mask": "r_mask_screen.png"},
    }
    return Plate(
        key="room/r-16x9", family="room", name="r-16x9", canvas=(200, 100),
        delivered=(400, 200), export_scale=2, aspect="16x9", playback="loop",
        fps=12.0, frame_count=len(frames),
        frames=tuple(Frame(tag=f"_f{i + 1:02d}", png=f,
                           front="r_front.png" if front else "")
                     for i, f in enumerate(frames)),
        files_png="r.png", files_svg="", base_is_frame="_f01", slots={},
        type_roles={}, root=tmp, layers={"front": "r_front.png"} if front else {},
        writable=writable)


def _red(img) -> np.ndarray:
    a = np.asarray(img).astype(int)
    return (a[..., 3] > 0) & (a[..., 0] > 120) & (a[..., 1] < 80)


def test_the_board_ticks_off_the_chapters_as_the_video_goes():
    """18 Oct 2026: the chapters before the one the video is in are ticked,
    its number and the ones before circled, in red; nothing else moves."""
    size = (900, 600)
    d = _dressing(closes=())        # no red price line to confuse the marks
    none = rd.board_ink(d, FONTS, size)
    two = rd.board_ink(d.in_chapter(2), FONTS, size)
    three = rd.board_ink(d.in_chapter(3), FONTS, size)
    assert not _red(none).any()
    assert _red(two).sum() > 50 and _red(three).sum() > _red(two).sum()
    # The episode's box, its ticker and the question are the same strokes in
    # every chapter: the hand is seeded by the episode, not the chapter.
    top = slice(0, int(0.35 * size[1]))
    assert np.array_equal(np.asarray(none)[top], np.asarray(three)[top])
    assert d.in_chapter(2).board_seed == d.board_seed == d.showing(None).board_seed
    assert d.in_chapter(2).fingerprint != d.fingerprint


def test_a_chapter_break_starts_from_the_board_the_last_chapter_left():
    """Nothing of the new marks drawn is the board as the chapter before had
    it; the tick then the ring go on a stroke at a time."""
    size = (900, 600)
    d = _dressing(closes=())
    before = np.asarray(rd.board_ink(d.in_chapter(1), FONTS, size))
    start = np.asarray(rd.board_ink(d.in_chapter(2), FONTS, size, tick=0.0, ring=0.0))
    assert np.array_equal(before, start)
    half = rd.board_ink(d.in_chapter(2), FONTS, size, tick=0.5, ring=0.0)
    ticked = rd.board_ink(d.in_chapter(2), FONTS, size, tick=1.0, ring=0.0)
    done = rd.board_ink(d.in_chapter(2), FONTS, size)
    reds = [_red(x).sum() for x in (start, half, ticked, done)]
    assert reds == sorted(reds) and len(set(reds)) == 4, reds


def test_the_break_is_drawn_on_the_room_at_the_markers_pace(tmp_path):
    plate = _plate(tmp_path / "kit", frames=("r.png",))
    d = _dressing(closes=()).in_chapter(2)
    frames = rd.tick_frames(plate, d, FONTS, (400, 200))
    assert len(frames) == round(rd.TICK_CLIP_S * rd.REVEAL_FPS)
    rooms = [np.asarray(r) for r, _ in frames]
    assert all(f is not None for _, f in frames)
    # still until the tick, drawing through the ring, then held
    changed = [i for i in range(1, len(rooms)) if not np.array_equal(rooms[i], rooms[i - 1])]
    assert changed[0] == rd.TICK_AT
    assert changed[-1] == rd.RING_AT + rd.RING_FRAMES - 1
    # a room that loops keeps looping under the marker
    looped = rd.tick_frames(_plate(tmp_path / "loop"), d, FONTS, (400, 200))
    assert not np.array_equal(np.asarray(looped[1][0]), np.asarray(looped[2][0]))
    # The first chapter has no break, and one past the board's list has none.
    assert rd.tick_frames(plate, d.in_chapter(1), FONTS, (400, 200)) is None
    assert rd.tick_frames(plate, d.in_chapter(4), FONTS, (400, 200)) is None


def test_a_written_room_is_the_same_room_rooted_elsewhere(tmp_path):
    plate = _plate(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "written", FONTS)
    assert out is not plate and out.root != plate.root
    assert out.key == plate.key and not out.writable
    # The kit's frames, in order.
    assert [f.png for f in out.frames] == [f.png for f in plate.frames]
    for p in [out.path, *out.frame_paths(), out.front_path(0)]:
        assert p.exists() and Image.open(p).size == (400, 200)
    # Written once: a second call finds it and writes nothing.
    stamp = out.path.stat().st_mtime_ns
    again = rd.written_room(plate, _dressing(), tmp_path / "written", FONTS)
    assert again.root == out.root and again.path.stat().st_mtime_ns == stamp
    # Another episode is another set of pictures.
    other = rd.written_room(plate, _dressing(episode=8), tmp_path / "written", FONTS)
    assert other.root != out.root


def test_the_writing_follows_the_room_light_and_what_stands_in_front(tmp_path):
    plate = _plate(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "written", FONTS)
    before = np.asarray(Image.open(plate.path).convert("RGB")).astype(int)
    after = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    board = (slice(10, 190), slice(10, 190))
    assert (after[board] < before[board] - 8).any(), "nothing was written on the board"
    assert (after[:, 90:110] == before[:, 90:110]).all(), \
        "the board's writing was drawn over what stands in front of it"
    # The screen's glow may lift the note a little; the chart is not on it.
    assert np.abs(after[12:28, 212:238] - before[12:28, 212:238]).max() < 40, \
        "the chart was drawn over the sticky note"
    # Off the surfaces nothing changes, but for the screen's glow beside it.
    assert (after[:5, :170] == before[:5, :170]).all()

    # THE DIP: the screen frame at 55% shows the same chart at 55%.
    bright = _lin(after[40:190, 215:385])
    dim = _lin(np.asarray(Image.open(out.frame_paths()[2]).convert("RGB"))[40:190, 215:385])
    big = bright > 0.05
    assert np.allclose(dim[big] / bright[big], 0.55, atol=0.06)


def test_the_front_carries_the_written_monitor_and_stays_clear_elsewhere(tmp_path):
    plate = _plate(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "written", FONTS)
    front = np.asarray(Image.open(out.front_path(0)))
    room = np.asarray(Image.open(out.path).convert("RGB"))
    assert front.shape[2] == 4
    assert (front[150:190, 250:350, :3] == room[150:190, 250:350]).all(), \
        "the desk in front of him shows a different monitor from the room behind"
    assert (front[..., 3] == 0).sum() and (front[front[..., 3] == 0][:, :3] == 0).all()


def test_a_room_with_nothing_to_write_on_is_itself(tmp_path):
    plate = _plate(tmp_path / "kit")
    from dataclasses import replace

    bare = replace(plate, writable={})
    assert rd.written_room(bare, _dressing(), tmp_path / "w", FONTS) is bare


def test_the_episode_number_counts_the_longs(settings):
    rows = [
        {"ticker": "AAA", "video_id": "1", "title": "a", "privacy": "public",
         "workdate": "2026-09-01", "uploaded_at": "2026-09-01T10:00", "fmt": "long"},
        {"ticker": "BBB", "video_id": "2", "title": "b", "privacy": "public",
         "workdate": "2026-09-02", "uploaded_at": "2026-09-02T10:00", "fmt": "short"},
        {"ticker": "CCC", "video_id": "3", "title": "c", "privacy": "public",
         "workdate": "2026-09-03", "uploaded_at": "2026-09-03T10:00", "fmt": "long"},
        # The same long, uploaded again, keeps its number.
        {"ticker": "AAA", "video_id": "4", "title": "a2", "privacy": "public",
         "workdate": "2026-09-01", "uploaded_at": "2026-09-04T10:00", "fmt": "long"},
    ]
    from pipeline.youtube import RECORDS_FILE

    path = settings.state_dir / RECORDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert rd.episode_number(settings, "aaa", "2026-09-01") == 1
    assert rd.episode_number(settings, "CCC", "2026-09-03") == 2
    assert rd.episode_number(settings, "DDD", "2026-10-03") == 3


def _records(settings, rows) -> None:
    from pipeline.youtube import RECORDS_FILE

    path = settings.state_dir / RECORDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def _long(ticker: str, day: str, *, privacy: str = "public", fmt: str = "long", vid: str = ""):
    return {"ticker": ticker, "video_id": vid or f"{ticker}{day}", "title": ticker,
            "privacy": privacy, "workdate": day, "uploaded_at": f"{day}T10:00", "fmt": fmt}


def test_the_10k_pile_counts_the_longs_gone_public_before_this_video(settings):
    """V12: a report for every long on record as public and dated no later
    than the video; not a short, not one still private or unlisted, not the
    long being made, and a long uploaded twice once."""
    _records(settings, [
        _long("AAA", "2026-09-01"), _long("BBB", "2026-09-02", fmt="short"),
        _long("CCC", "2026-09-03"), _long("AAA", "2026-09-01", vid="again"),
        _long("DDD", "2026-09-04", privacy="unlisted"), _long("EEE", "2026-09-05", privacy="private"),
        _long("FFF", "2026-10-20")])
    assert rd.pile_count(settings, "GGG", "2026-10-01", long=True) == 2
    assert rd.pile_count(settings, "ccc", "2026-09-03", long=True) == 1, \
        "the long being made is on the pile before it went public"
    assert rd.pile_count(settings, "CCC", "2026-09-03", long=False) == 2
    assert rd.pile_count(settings, "ZZZ", "2026-08-01", long=True) == 0
    _records(settings, [_long(f"T{i:02d}", f"2026-0{1 + i % 9}-1{i % 10}") for i in range(60)])
    assert rd.pile_count(settings, "ZZZ", "2026-12-31", long=True) == rd.PILE_MAX == 48


def test_no_record_is_no_pile(settings):
    assert rd.pile_count(settings, "EXMPL", "2026-10-01", long=True) == 0


def test_the_pile_is_a_new_room_but_the_board_keeps_its_hand():
    d = _dressing()
    assert _dressing(pile=3).fingerprint != d.fingerprint
    assert _dressing(pile=3).board_seed == d.board_seed


def _pile_png(tmp: Path, size=(400, 200)) -> Path:
    """The 10-Ks alone at the room's size: the reports opaque, their shadow
    half dark, nothing else."""
    k = size[0] / 400
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    im.paste((200, 30, 30, 255), (int(20 * k), int(150 * k), int(60 * k), int(190 * k)))
    im.paste((0, 0, 0, 128), (int(60 * k), int(170 * k), int(90 * k), int(190 * k)))
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"pile{size[0]}.png"
    im.save(path)
    return path


def test_the_10k_pile_is_laid_on_every_picture_but_the_front(tmp_path):
    plate = _plate(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(pile=5), tmp_path / "written", FONTS,
                          pile=_pile_png(tmp_path / "p"))
    before = np.asarray(Image.open(plate.path).convert("RGB")).astype(int)
    for p in [out.path, *out.frame_paths()]:
        a = np.asarray(Image.open(p).convert("RGB")).astype(int)
        assert (a[155:185, 25:55] == (200, 30, 30)).all(), f"no pile on {p.name}"
    after = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    assert (after[175:188, 65:85] < before[175:188, 65:85] - 20).all(), "no shadow under it"
    front = np.asarray(Image.open(out.front_path(0)))
    assert front[150:190, 20:90, 3].max() == 0, "the pile went in front of him"
    # Without the pile the same episode is its own set of pictures.
    bare = rd.written_room(plate, _dressing(pile=5), tmp_path / "written", FONTS)
    assert bare.root != out.root


def test_a_room_with_only_the_pile_to_lay_is_written_and_a_draft_s_pile_scaled(tmp_path):
    from dataclasses import replace

    plate = replace(_plate(tmp_path / "kit"), writable={})
    out = rd.written_room(plate, _dressing(pile=5), tmp_path / "written", FONTS,
                          pile=_pile_png(tmp_path / "p", size=(200, 100)))
    assert out is not plate
    a = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    assert (np.abs(a[160:180, 30:50] - (200, 30, 30)) < 6).all()


def test_the_writer_sets_the_board(long_valid_text, settings):
    from pipeline.models import TagType
    from pipeline.parser_long import parse_long_script

    text = "[BOARD:   who pays   for the buyback? ]\n" + long_valid_text
    script, _ = parse_long_script(text, "EXMPL", settings)
    boards = [e for e in script.events if e.type is TagType.BOARD]
    assert [e.payload for e in boards] == ["who pays for the buyback?"]
    assert rd.board_question(script) == "who pays for the buyback?"
    plain, _ = parse_long_script(long_valid_text, "EXMPL", settings)
    assert rd.board_question(plain) == rd.BOARD_DEFAULT_QUESTION


def test_a_board_tag_draws_no_cue_and_is_not_reported_as_dropped(long_valid_text, settings):
    from pipeline.parser_long import parse_long_script
    from pipeline.timeline import unrenderable_long_tags

    script, _ = parse_long_script("[BOARD: what is it worth?]\n" + long_valid_text,
                                  "EXMPL", settings)
    assert not [e for e, _ in unrenderable_long_tags(script) if e.type.value == "BOARD"]


def test_a_board_naming_the_vendor_is_refused(long_valid_text, settings):
    from pipeline.parser_long import VENDOR_WORDS, LongScriptError, parse_long_script

    word = sorted(VENDOR_WORDS)[0]
    with pytest.raises(LongScriptError, match="BOARD"):
        parse_long_script(f"[BOARD: per {word}]\n" + long_valid_text, "EXMPL", settings)


# ------------------------------------------------- the monitor (49, 54)
def _board_only(tmp: Path, *, still: bool = True) -> Plate:
    from dataclasses import replace

    plate = _plate(tmp)
    plate = replace(plate, writable={"board": plate.writable["board"]})
    if still:
        plate = replace(plate, playback="static", fps=0.0, frame_count=1,
                        frames=plate.frames[:1])
    return plate


def _still(tmp: Path) -> Plate:
    from dataclasses import replace

    plate = _plate(tmp)
    return replace(plate, playback="static", fps=0.0, frame_count=1,
                   frames=plate.frames[:1])


def _picture(tmp: Path) -> Path:
    """A plate's picture: warm paper with a red bar, so it is easy to find."""
    pic = np.zeros((90, 160, 3), np.uint8)
    pic[:] = (236, 226, 204)
    pic[30:80, 20:140] = (200, 40, 40)
    path = tmp / "pic.png"
    tmp.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pic).save(path)
    return path


def test_the_glass_is_all_picture_and_the_room_holds_still(tmp_path):
    """The room's made-up app (a sidebar of bars round the chart area) goes
    under the picture, and a room that held still still does: nothing on
    the monitor moves but the chapter's picture drawing in."""
    plate = _still(tmp_path / "kit")
    before = np.asarray(Image.open(plate.path).convert("RGB")).astype(int)
    out = rd.written_room(plate, _dressing().showing(_picture(tmp_path), "The cash"),
                          tmp_path / "w", FONTS)
    assert not out.animated and len(out.frames) <= 1
    after = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    side = after[40:160, 356:380]
    assert (np.abs(before[40:160, 356:380] - APP).max() < 3), "the fixture has no app"
    assert side.mean() > 150, "the app's sidebar still shows on the glass"
    # The picture's own paper, not the backlight's grey.
    assert side[..., 0].mean() > side[..., 2].mean()


def test_the_glass_is_drawn_at_its_own_shape(tmp_path):
    """The glass is wider than the 16:9 texture stretched over it: a square
    on the picture must come out square in the room."""
    sq = np.full((90, 160, 3), 240, np.uint8)
    sq[25:65, 60:100] = (200, 40, 40)
    pic = tmp_path / "sq.png"
    Image.fromarray(sq).save(pic)
    plate = _still(tmp_path / "kit")
    from dataclasses import replace

    # A front-on glass in the room as wide as the real one is for its height.
    h = 60
    w = h * rd.GLASS_ASPECT
    x0, y0 = 100 + (100 - w) / 2, 20
    chart = [[x0 + w * x / 1920, y0 + h * y / 1080]
             for x, y in ((60, 116), (1392, 116), (1392, 1044), (60, 1044))]
    plate = replace(plate, writable={"screen": {**plate.writable["screen"], "quad": chart}})
    out = rd.written_room(plate, _dressing().showing(pic, "x"), tmp_path / "w", FONTS)
    img = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    red = (img[..., 0] > img[..., 1] + 60) & (img[..., 0] > img[..., 2] + 60)
    ys, xs = np.nonzero(red)
    assert abs((xs.max() - xs.min()) / (ys.max() - ys.min()) - 1) < 0.08


def test_a_board_only_room_still_holds_still(tmp_path):
    plate = _board_only(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "w", FONTS)
    assert not out.animated and out.frames == plate.frames


def test_a_room_that_loops_keeps_its_frames_each_written(tmp_path):
    plate = _plate(tmp_path / "kit", frames=tuple("r.png" if i != 3 else "r_f03.png"
                                                  for i in range(12)))
    out = rd.written_room(plate, _dressing(), tmp_path / "w", FONTS)
    assert out.frames == plate.frames and out.fps == plate.fps
    for p in out.frame_paths():
        assert p.exists() and tmp_path / "w" in p.parents


def test_the_monitor_shows_the_chapters_picture(tmp_path):
    pic = _picture(tmp_path)
    d = _dressing()
    shown = d.showing(pic, "The cash")
    assert shown.fingerprint != d.fingerprint
    assert d.showing(None) == d and shown.showing(None).fingerprint == d.fingerprint
    tex = np.asarray(rd.screen_chart(shown, FONTS, (666, 308)))
    red = (tex[..., 0] > 170) & (tex[..., 1] < 70)
    assert red.mean() > 0.2, "the plate's picture is not on the monitor"
    # Not the price's line.
    assert not ((tex[..., 2] > 120) & (tex[..., 0] < 80)).sum() > 400
    # A new picture is a new written room.
    plate = _still(tmp_path / "kit")
    a = rd.written_room(plate, d, tmp_path / "w", FONTS)
    b = rd.written_room(plate, shown, tmp_path / "w", FONTS)
    assert a.root != b.root


def test_the_picture_draws_itself_in(tmp_path):
    pic = _picture(tmp_path)
    shown = _dressing().showing(pic, "The cash")
    red = lambda im: ((im[..., 0] > 170) & (im[..., 1] < 70)).sum()  # noqa: E731
    steps = [red(np.asarray(rd.screen_chart(shown, FONTS, (666, 308), reveal=r)))
             for r in (0.0, 0.3, 0.6, 1.0)]
    assert steps[0] == 0 and steps[0] < steps[1] < steps[2] < steps[3]
    line = lambda im: ((im[..., 2] > 120) & (im[..., 0] < 80)).sum()  # noqa: E731
    price = [line(np.asarray(rd.screen_chart(_dressing(), FONTS, (666, 308), reveal=r)))
             for r in (0.0, 0.5, 1.0)]
    assert price[0] == 0 and price[0] < price[1] < price[2]


def test_reveal_frames_end_on_the_written_room(tmp_path):
    plate = _still(tmp_path / "kit")
    d = _dressing().showing(_picture(tmp_path), "The cash")
    frames = rd.reveal_frames(plate, d, FONTS, (400, 200))
    assert len(frames) == rd.REVEAL_FRAMES and all(f is not None for _, f in frames)
    out = rd.written_room(plate, d, tmp_path / "w", FONTS)
    last = np.asarray(frames[-1][0]).astype(int)
    written = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    assert np.abs(last - written).max() <= 2, "the draw-in does not land on the room"
    first = np.asarray(frames[0][0]).astype(int)
    assert np.abs(first - written).sum() > 0
    assert rd.reveal_frames(_board_only(tmp_path / "kit2"), d, FONTS, (400, 200)) is None


def test_the_picture_s_corners_are_where_it_is_drawn(tmp_path):
    """Item 60 pushes the camera into these corners: they must be the picture."""
    plate = _still(tmp_path / "kit")
    pic = tmp_path / "solid.png"
    # Red to its paper edge: the glass round the picture takes the paper.
    solid = Image.new("RGB", (160, 90), (240, 238, 230))
    solid.paste((200, 40, 40), (1, 1, 159, 89))
    solid.save(pic)
    d = _dressing().showing(pic, "The cash")
    q = rd.picture_quad(plate, d, (400, 200))
    assert q is not None and len(q) == 4
    out = rd.written_room(plate, d, tmp_path / "w", FONTS)
    img = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    red = (img[..., 0] > img[..., 1] + 60) & (img[..., 0] > img[..., 2] + 60)
    red[:, :200] = False            # the board's red line is not the picture
    ys, xs = np.nonzero(red)
    xs_q, ys_q = [p[0] for p in q], [p[1] for p in q]
    assert abs(xs.min() - min(xs_q)) <= 3 and abs(xs.max() + 1 - max(xs_q)) <= 3
    assert abs(ys.min() - min(ys_q)) <= 3 and abs(ys.max() + 1 - max(ys_q)) <= 3
    assert rd.picture_quad(plate, _dressing(), (400, 200)) is None
    assert rd.picture_quad(_board_only(tmp_path / "kit2"), d, (400, 200)) is None


# ---------------------------------------------------------- the phone's rooms
def test_a_short_s_board_leads_with_the_ticker():
    """A short has no number in the channel's run: no EP box, the ticker
    where it was."""
    size = (900, 600)
    top = slice(0, int(0.3 * size[1]))

    def right_edge(im):
        a = np.asarray(im)[top, :, 3]
        return np.nonzero(a.max(axis=0))[0].max()

    long_ = rd.board_ink(_dressing(), FONTS, size)
    short = rd.board_ink(_dressing(episode=0, chapters=()), FONTS, size)
    assert right_edge(short) < right_edge(long_) - 100, "the ticker did not move up"
    assert (np.asarray(short)[..., 3] > 0).mean() > 0.01


def test_the_short_writes_on_the_rooms_it_cuts_to(tmp_path):
    from types import SimpleNamespace

    from pipeline.compose import BuildResult, Layer
    from pipeline.render_short import dress_rooms

    plate = _plate(tmp_path / "kit", frames=("r.png",))
    plate = Plate(**{**plate.__dict__, "playback": "static", "fps": 0.0})
    reg = SimpleNamespace(get=lambda k: plate if k == plate.key else None, base_hour="night")
    layers = [Layer("t:plate", "plate", "the-turn", 1.0, 4.0, entry_key=plate.key),
              Layer("t:host", "host", "the-turn", 1.0, 4.0, entry_key="host/close-up")]
    result = BuildResult(layers=layers, spans=[], frame=(1080, 1920))
    settings = SimpleNamespace(price_history_days=120, fonts_dir=FONTS,
                               assets_dir=FONTS.parent)
    prices = SimpleNamespace(closes=list(CLOSES), degraded=False)
    got, rooms = dress_rooms(result, reg, ticker="exmpl", prices=prices,
                             workdir=tmp_path / "w", settings=settings)
    assert rooms == [plate.key]
    w = got.get(plate.key)
    assert w is not plate and (tmp_path / "w" / "written") in w.root.parents
    assert got.base_hour == "night", "the rest is asked of the registry"
    # A room that held still still does.
    room = result.layers[0]
    assert (room.frame_count, room.loops) == (1, False)
    assert result.layers[1].frame_count == 1
    # Nothing in the cut with a board or a monitor: the registry as it was.
    bare = BuildResult(layers=[layers[1]], spans=[], frame=(1080, 1920))
    assert dress_rooms(bare, reg, ticker="X", prices=None, workdir=tmp_path / "w2",
                       settings=settings) == (reg, [])


def test_the_short_lays_the_10k_pile_on_its_rooms(tmp_path):
    """V12 in the short: the performer draws the pile at the room's angle
    and every picture of the room gets it, the front excepted; a room the
    pile is not in shot of is written as it was."""
    from dataclasses import replace
    from types import SimpleNamespace

    from pipeline.compose import BuildResult, Layer
    from pipeline.render_short import dress_rooms

    plate = _plate(tmp_path / "kit")
    bare = replace(plate, key="room/b-16x9", name="b-16x9", writable={})
    plates = {p.key: p for p in (plate, bare)}
    reg = SimpleNamespace(get=plates.get, base_hour="night")
    asked = []
    pile_png = _pile_png(tmp_path / "p")

    def pile_layer(room, size):
        asked.append((room.key, size))
        return pile_png if room.key == plate.key else None

    performer = SimpleNamespace(pile_layer=pile_layer)
    layers = [Layer("t:plate", "plate", "the-turn", 1.0, 4.0, entry_key=plate.key),
              Layer("b:plate", "plate", "the-bare", 4.0, 6.0, entry_key=bare.key)]
    result = BuildResult(layers=layers, spans=[], frame=(1080, 1920))
    settings = SimpleNamespace(price_history_days=120, fonts_dir=FONTS,
                               assets_dir=FONTS.parent)
    prices = SimpleNamespace(closes=list(CLOSES), degraded=False)
    got, rooms = dress_rooms(result, reg, ticker="exmpl", prices=prices,
                             workdir=tmp_path / "w", settings=settings, pile=4,
                             performer=performer)
    assert asked == [(plate.key, (400, 200)), (bare.key, (400, 200))]
    assert rooms == [plate.key], "the room with nothing to write and no pile in shot is itself"
    w = got.get(plate.key)
    a = np.asarray(Image.open(w.path).convert("RGB")).astype(int)
    assert (a[155:185, 25:55] == (200, 30, 30)).all()
    assert np.asarray(Image.open(w.front_path(0)))[150:190, 20:90, 3].max() == 0


def test_the_push_in_reads_his_pixels_not_his_rectangle(tmp_path):
    """The push-in (item 60) is refused where he is over the monitor's
    picture. His clip's rectangle overlaps the monitor in every desk room;
    what counts is whether HE does, at any frame of the push."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    from pipeline.render_long import _host_covers_picture

    frames = tmp_path / "f"
    frames.mkdir()
    for k in range(10):
        im = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        # He stands in the left half; from frame 6 his arm reaches right.
        im.paste((200, 150, 120, 255), (10, 40, 50, 200))
        if k >= 6:
            im.paste((200, 150, 120, 255), (50, 60, 95, 75))
        im.save(frames / f"{k:03d}.png")
    clip = tmp_path / "host.mov"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "10", "-i",
                    str(frames / "%03d.png"), "-c:v", "png", "-pix_fmt", "rgba", str(clip)],
                   check=True)
    box = (300, 100, 100, 200)                    # his clip, placed at x 300..400
    quad = [(360, 120), (480, 120), (480, 200), (360, 200)]   # the picture, x 360..480
    assert not _host_covers_picture(clip, box, quad, 0.0, 0.5, (640, 360)), \
        "his rectangle overlaps the picture but he does not"
    assert _host_covers_picture(clip, box, quad, 0.4, 0.5, (640, 360)), \
        "his arm reaches into the picture at frame 6"
    # Past the clip's end the beat holds his last frame, arm out.
    assert _host_covers_picture(clip, box, quad, 3.0, 0.5, (640, 360))


def test_the_pull_back_starts_on_the_chart_and_ends_on_the_room():
    """18 Oct 2026: a chapter ending on a full-screen chart backs out of it,
    from the plate filling the frame to the room with it on the monitor."""
    room = Image.new("RGB", (800, 450), (30, 34, 60))
    quad = [(400.0, 100.0), (640.0, 110.0), (630.0, 250.0), (405.0, 240.0)]
    from PIL import ImageDraw

    ImageDraw.Draw(room).polygon(quad, fill=(200, 200, 190))
    pic = Image.new("RGB", (320, 180), PAPER)
    ImageDraw.Draw(pic).rectangle([40, 60, 120, 170], fill=(40, 60, 154))
    frames = rd.pull_back_frames(room, quad, pic, (320, 180), 30)
    assert len(frames) == round(rd.PULL_S * 30) + round(rd.PULL_HOLD_S * 30)
    first, last = np.asarray(frames[0], float), np.asarray(frames[-1], float)
    assert np.abs(first - np.asarray(pic, float)).mean() < 6, "it does not start on the chart"
    assert np.abs(last - np.asarray(room.resize((320, 180)), float)).mean() < 6
    # the room comes up round the chart: more of the room's ink each frame
    dark = [(np.asarray(f, float).mean(axis=2) < 80).mean() for f in frames]
    n = round(rd.PULL_S * 30)
    assert all(b >= a - 1e-3 for a, b in itertools.pairwise(dark[:n]))
    assert frames[n - 1].tobytes() == frames[-1].tobytes()


def _clock_room(tmp: Path) -> Path:
    """A committed-renders folder with a clock close-up: the face a pale disc
    at the middle of a 640x360 picture, its hands left to the bot."""
    from PIL import ImageDraw

    face = (234, 232, 224)
    pic = Image.new("RGB", (1920, 1080), (40, 50, 90))
    ImageDraw.Draw(pic).ellipse([660, 240, 1260, 840], fill=face)
    pic.save(tmp / "clock.jpg")
    mask = Image.new("L", (1920, 1080), 0)
    ImageDraw.Draw(mask).ellipse([660, 240, 1260, 840], fill=255)
    mask.save(tmp / "clock_mask_labels.png")
    item = {"id": "clockface", "kind": "clock", "paper": list(face), "tex": [600, 600],
            "box": [0, 0, 600, 600], "depth": 1.0,
            "quad": [[660, 240], [1260, 240], [1260, 840], [660, 840]]}
    (tmp / "rooms.json").write_text(json.dumps({"clock": {
        "angle": "clock", "aspect": "16x9", "season": "plain",
        "states": [{"png": "clock.jpg", "tag": ""}],
        "masks": {"labels": "clock_mask_labels.png"},
        "surfaces": {"labels": {"items": [item]}}}}), encoding="utf-8")
    return tmp


def _ink_along(img, minutes: float, *, size=(640, 360), reach=0.3) -> float:
    """How dark the face is `reach` of its radius out along `minutes`' hand."""
    import math

    a = minutes / 60 * 2 * math.pi
    cx, cy, r = size[0] / 2, size[1] / 2, size[1] * 300 / 1080
    x, y = cx + reach * r * math.sin(a), cy - reach * r * math.cos(a)
    return float(np.asarray(img.convert("L"))[int(y) - 1:int(y) + 2, int(x) - 1:int(x) + 2].mean())


def test_the_clock_jump_runs_the_hands_on_half_an_hour(tmp_path):
    """18 Oct 2026, transition 4: into a long video's last beat, the wall
    clock close, its hands running on half an hour. The face is rendered
    bare; the hands are the bot's."""
    assert rd.clock_minutes("3:05") == 185 and rd.clock_text(215) == "3:35"
    assert rd.clock_text(rd.clock_minutes("12:40")) == "12:40"
    shot = rd.clock_shot(_clock_room(tmp_path))
    assert shot is not None
    assert rd.clock_shot(tmp_path / "nowhere") is None
    frames = rd.clock_jump_frames(shot, FONTS, (640, 360), 30, 185, 215)
    assert len(frames) == sum(round(x * 30) for x in (rd.CLOCK_HOLD_S, rd.CLOCK_SWEEP_S,
                                                      rd.CLOCK_AFTER_S))
    first, last = frames[0], frames[-1]
    # the minute hand on the one at 3:05, on the seven at 3:35
    assert _ink_along(first, 5) < 120 < _ink_along(first, 35)
    assert _ink_along(last, 35) < 120 < _ink_along(last, 5)
    # it holds, sweeps, holds
    hold = round(rd.CLOCK_HOLD_S * 30)
    assert frames[0].tobytes() == frames[hold - 1].tobytes()
    assert frames[-1].tobytes() == frames[-2].tobytes()
    assert len({f.tobytes() for f in frames}) > 8



# ------------------------------------------- the plant's tag and his phone
_TAG = {"id": "plant-tag", "kind": "plant", "paper": [242, 242, 236], "tex": [360, 200],
        "box": [20, 24, 340, 176], "quad": [[20, 20], [56, 20], [56, 40], [20, 40]], "depth": 2.0}
_PHONE = {"id": "phonescreen", "kind": "phone", "paper": [16, 18, 24], "tex": [400, 800],
          "box": [28, 150, 372, 470], "quad": [[120, 20], [160, 20], [160, 90], [120, 90]],
          "depth": 1.5}


def _labelled(tmp: Path) -> Plate:
    """A dark room, 200x100 canvas delivered at 400x200, with a plant's tag
    painted (242, 242, 236) on the left and the phone's dark glass right."""
    from PIL import ImageDraw

    fam = tmp / "room"
    fam.mkdir(parents=True)
    room = Image.new("RGB", (400, 200), (24, 28, 40))
    mask = Image.new("L", (400, 200), 0)
    for item in (_TAG, _PHONE):
        quad = [(x * 2, y * 2) for x, y in item["quad"]]
        ImageDraw.Draw(room).polygon(quad, fill=tuple(item["paper"]))
        ImageDraw.Draw(mask).polygon(quad, fill=255)
    room.save(fam / "r.png")
    mask.save(fam / "r_mask_labels.png")
    return Plate(
        key="room/r-16x9", family="room", name="r-16x9", canvas=(200, 100),
        delivered=(400, 200), export_scale=2, aspect="16x9", playback="static",
        fps=0.0, frame_count=1, frames=(Frame(tag="", png="r.png", front=""),),
        files_png="r.png", files_svg="", base_is_frame=None, slots={}, type_roles={},
        root=tmp, layers={},
        writable={"labels": {"items": [_TAG, _PHONE], "mask": "r_mask_labels.png"}})


def test_the_plant_is_named_in_marker_on_its_tag(tmp_path):
    plate = _labelled(tmp_path / "kit")
    d = _dressing(props=(("plant-tag", "EXMPL"),))
    out = rd.written_room(plate, d, tmp_path / "w", FONTS)
    before = np.asarray(Image.open(plate.path).convert("RGB")).astype(int)
    after = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    tag = (slice(42, 78), slice(42, 110))
    assert (after[tag] < before[tag] - 60).sum() > 40, "no name in marker on the tag"
    assert (after[:, 200:] == before[:, 200:]).all(), "a dark phone was lit with nothing to say"


def test_kev_s_message_lights_the_phone_and_it_shines(tmp_path):
    """Pick 7: the glass is lit, brighter than the dark render everywhere
    on it, with the notification's pale bubble, and spills past its edge."""
    plate = _labelled(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(props=(("phonescreen", "Kev: thoughts?"),)),
                          tmp_path / "w", FONTS)
    before = np.asarray(Image.open(plate.path).convert("RGB")).astype(int)
    after = np.asarray(Image.open(out.path).convert("RGB")).astype(int)
    glass = after[44:176, 244:316]
    assert (glass.mean(axis=2) > before[44:176, 244:316].mean(axis=2)).mean() > 0.95
    assert (glass.min(axis=2) > 180).sum() > 60, "no notification on the glass"
    beside = (slice(60, 160), slice(324, 334))
    assert (after[beside] >= before[beside]).all() and (after[beside] > before[beside]).any(), \
        "a lit phone in a dark room spills a little light"
    assert (after[:, :150] == before[:, :150]).all(), "the phone's light reached across the room"
