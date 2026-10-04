"""The episode written in the 3D room: the board and the monitor (item 36)."""

from __future__ import annotations

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
    assert not ((chart[..., 1] > 180) & (chart[..., 2] > 220)).any(), \
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
        "screen": {"quad": [[105, 5], [195, 5], [195, 95], [105, 95]],
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


def test_a_written_room_is_the_same_room_rooted_elsewhere(tmp_path):
    plate = _plate(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "written", FONTS)
    assert out is not plate and out.root != plate.root
    assert out.key == plate.key and not out.writable
    # The kit's frames, in order, round to a whole second of the cursor.
    assert [f.png.replace(".off", "") for f in out.frames] == \
        [plate.frames[i % 3].png for i in range(12)]
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
    assert (after[12:28, 212:238] == before[12:28, 212:238]).all(), \
        "the chart was drawn over the sticky note"
    # Off the surfaces nothing changes.
    assert (after[:5] == before[:5]).all()

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


def test_a_still_room_with_the_monitor_in_shot_loops_its_cursor(tmp_path):
    out = rd.written_room(_still(tmp_path / "kit"), _dressing(), tmp_path / "w", FONTS)
    assert out.animated and out.playback == "loop" and out.fps == rd.BLINK_FPS
    assert out.frame_count == rd.BLINK_FRAMES == len(out.frames)
    on, off = out.frame_paths()[0], out.frame_paths()[-1]
    assert out.frame_paths()[:6] == [on] * 6 and out.frame_paths()[6:] == [off] * 6
    a = np.asarray(Image.open(on).convert("RGB")).astype(int)
    b = np.asarray(Image.open(off).convert("RGB")).astype(int)
    diff = np.abs(a - b).sum(axis=2) > 0
    assert diff.any(), "the cursor does not blink"
    ys, xs = np.nonzero(diff)
    # Only on the monitor, and only along its prompt line at the bottom.
    assert xs.min() >= 200 and ys.min() > 150, "the blink touched more than the prompt"
    # The desk in front blinks with it.
    assert out.front_path(0) != out.front_path(11)
    assert out.front_path(11).exists()


def test_a_board_only_room_still_holds_still(tmp_path):
    plate = _board_only(tmp_path / "kit")
    out = rd.written_room(plate, _dressing(), tmp_path / "w", FONTS)
    assert not out.animated and out.frames == plate.frames


def test_a_room_that_loops_keeps_its_frames_and_blinks_on_them(tmp_path):
    from dataclasses import replace

    plate = _plate(tmp_path / "kit", frames=tuple("r.png" if i != 3 else "r_f03.png"
                                                  for i in range(12)))
    out = rd.written_room(plate, _dressing(), tmp_path / "w", FONTS)
    assert out.frame_count == 12
    assert out.frames[3].png == "r_f03.png" and out.frames[9].png == "r.off.png"
    assert all(f.front.endswith(".off.png") == (i >= 6) for i, f in enumerate(out.frames))
    # Nothing else of the room's own loop changes.
    assert replace(out.frames[3], png="", front="") == replace(plate.frames[3], png="", front="")


def test_the_monitor_shows_the_chapters_picture(tmp_path):
    pic = _picture(tmp_path)
    d = _dressing()
    shown = d.showing(pic, "The cash")
    assert shown.fingerprint != d.fingerprint
    assert d.showing(None) == d and shown.showing(None).fingerprint == d.fingerprint
    tex = np.asarray(rd.screen_chart(shown, FONTS, (666, 464)))
    red = (tex[..., 0] > 170) & (tex[..., 1] < 70)
    assert red.mean() > 0.2, "the plate's picture is not on the monitor"
    # Not the price's line.
    assert not ((tex[..., 1] > 180) & (tex[..., 2] > 220) & (tex[..., 0] < 120)).sum() > 400
    # A new picture is a new written room.
    plate = _still(tmp_path / "kit")
    a = rd.written_room(plate, d, tmp_path / "w", FONTS)
    b = rd.written_room(plate, shown, tmp_path / "w", FONTS)
    assert a.root != b.root


def test_the_picture_draws_itself_in(tmp_path):
    pic = _picture(tmp_path)
    shown = _dressing().showing(pic, "The cash")
    red = lambda im: ((im[..., 0] > 170) & (im[..., 1] < 70)).sum()  # noqa: E731
    steps = [red(np.asarray(rd.screen_chart(shown, FONTS, (666, 464), reveal=r)))
             for r in (0.0, 0.3, 0.6, 1.0)]
    assert steps[0] == 0 and steps[0] < steps[1] < steps[2] < steps[3]
    line = lambda im: ((im[..., 1] > 180) & (im[..., 2] > 220)).sum()  # noqa: E731
    price = [line(np.asarray(rd.screen_chart(_dressing(), FONTS, (666, 464), reveal=r,
                                             cursor=False)))
             for r in (0.0, 0.5, 1.0)]
    assert price[0] == 0 and price[0] < price[1] < price[2]


def test_reveal_frames_end_on_the_written_room(tmp_path):
    plate = _still(tmp_path / "kit")
    d = _dressing().showing(_picture(tmp_path), "The cash")
    frames = rd.reveal_frames(plate, d, FONTS, (400, 200))
    assert len(frames) == rd.REVEAL_FRAMES and all(f is not None for _, f in frames)
    out = rd.written_room(plate, d, tmp_path / "w", FONTS)
    last = np.asarray(frames[-1][0]).astype(int)
    written = np.asarray(Image.open(out.frame_paths()[0]).convert("RGB")).astype(int)
    assert np.abs(last - written).max() <= 2, "the draw-in does not land on the loop"
    first = np.asarray(frames[0][0]).astype(int)
    assert np.abs(first - written).sum() > 0
    assert rd.reveal_frames(_board_only(tmp_path / "kit2"), d, FONTS, (400, 200)) is None


def test_the_picture_s_corners_are_where_it_is_drawn(tmp_path):
    """Item 60 pushes the camera into these corners: they must be the picture."""
    plate = _still(tmp_path / "kit")
    pic = tmp_path / "solid.png"
    Image.new("RGB", (160, 90), (200, 40, 40)).save(pic)
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
    settings = SimpleNamespace(price_history_days=120, fonts_dir=FONTS)
    prices = SimpleNamespace(closes=list(CLOSES), degraded=False)
    got, rooms = dress_rooms(result, reg, ticker="exmpl", prices=prices,
                             workdir=tmp_path / "w", settings=settings)
    assert rooms == [plate.key]
    w = got.get(plate.key)
    assert w is not plate and (tmp_path / "w" / "written") in w.root.parents
    assert got.base_hour == "night", "the rest is asked of the registry"
    # The cursor blinks: the room layer loops now.
    room = result.layers[0]
    assert (room.frame_count, room.fps, room.loops) == (12, 12, True)
    assert result.layers[1].frame_count == 1
    # Nothing in the cut with a board or a monitor: the registry as it was.
    bare = BuildResult(layers=[layers[1]], spans=[], frame=(1080, 1920))
    assert dress_rooms(bare, reg, ticker="X", prices=None, workdir=tmp_path / "w2",
                       settings=settings) == (reg, [])
