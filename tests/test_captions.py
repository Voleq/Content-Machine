"""The SHORT's captions: where each one sits, and what is on it.

Two items, one file. Captions moved up out of the strip a phone covers with
the title, the channel name and the buttons, into design's safe band, and each
shot places its own clear of what that shot is showing. And a caption is two
to four words with the figure, or the one word that turns the sentence, in
`attention` — never word-by-word karaoke.

Placement is asserted on the layer list, the lines on the ASS text, and one
test burns a line with libass and measures the box, because "the box ends at
1560" is a claim about pixels that only a render can check.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.compose import (CAPTION_BAND, CAPTION_CLEARANCE_FH,
                              CAPTION_SIDE_FW, CAPTION_TYPE_FH, build_layers,
                              caption_band, caption_obstacles, place_caption)
from pipeline.models import WordTimestamp
from pipeline.plates import episode_hour, load_plates
from pipeline.rasters import (CAPTION_BOX_PAD, build_phrase_ass,
                              caption_box_height, contrast, figure_spans,
                              key_span, phrase_pages)
from pipeline.shots import expand_sequences, load_format, resolve_spans

SHORT_FRAME = (1080, 1920)


def _said(text: str, start: float = 0.0, step: float = 0.3) -> list[WordTimestamp]:
    return [WordTimestamp(word=w, start=start + i * step,
                          end=start + i * step + 0.25, char_start=0, char_end=0)
            for i, w in enumerate(text.split())]


def _dialogue(ass: str) -> list[list[str]]:
    """Each Dialogue line's ten fields, the text last and whole."""
    return [l.split(": ", 1)[1].split(",", 9) for l in ass.splitlines()
            if l.startswith("Dialogue:")]


def _style(ass: str) -> list[str]:
    return next(l for l in ass.splitlines()
                if l.startswith("Style: Caps,")).split(":", 1)[1].split(",")


def _rgb(ass_colour: str) -> tuple[int, int, int]:
    h = ass_colour.strip().strip("&H").strip("&")[-6:]          # BBGGRR
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def _keys(text: str) -> list[str]:
    """The colours a line switches to, in order: key on, back to ink."""
    return re.findall(r"\\1c(&H[0-9A-F]{6}&)", text)


def _short_words(settings) -> list[WordTimestamp]:
    """The fixture short's narration, tags out, at a speaking pace."""
    raw = json.loads(Path("fixtures/scripts/short_valid.json")
                     .read_text(encoding="utf-8"))["audio_script"]
    return _said(re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", raw)).strip())


def _short_lines(settings, words) -> list[list[WordTimestamp]]:
    return phrase_pages(words, max_words=4, max_chars=24, min_words=2)


def _counted(tokens: list[str]) -> int:
    """Words as a reader counts them: a figure is one, however it is said."""
    return len(tokens) - sum(e - s - 1 for s, e, _ in figure_spans(tokens))


# ---------------------------------------------------------------------------
# Two to four words
# ---------------------------------------------------------------------------

def test_a_short_caption_is_two_to_four_words(settings):
    """Five words at a time was most of every sentence on screen while the
    voice read it out. A line is two to four now, a figure counting as one
    word the way it would if it were typed 29% rather than said. The one
    exception is a sentence of one word: "Noise." joined to the next sentence
    would be a caption across a full stop."""
    lines = _short_lines(settings, _short_words(settings))
    assert len(lines) > 40
    for n, line in enumerate(lines):
        tokens = [w.word for w in line]
        counted = _counted(tokens)
        if counted == 1:
            before = lines[n - 1][-1].word if n else "."
            assert re.search(r"[.!?]$", tokens[-1]) and re.search(r"[.!?]$", before), \
                f"a one-word line that is not a sentence: {tokens}"
            continue
        assert 2 <= counted <= 4, tokens


def test_a_spoken_figure_is_never_split_across_two_captions(settings):
    """ "EXMPL is up twenty / nine percent today" is a different number on each
    line. A figure arrives whole or it is misread."""
    lines = _short_lines(settings, _short_words(settings))
    text = [" ".join(w.word for w in line) for line in lines]
    for figure in ("twenty nine percent", "five times", "eleven percent",
                   "four hundred million", "four ninety six",
                   "twenty twenty two",
                   "Two hundred and ninety eight million",
                   "three hundred and sixty five"):
        assert any(figure in t for t in text), (figure, text)


def test_a_line_breaks_on_the_clause_rather_than_after_four(settings):
    """Four-and-flush did "Margins fell again this / quarter." Balanced, the
    same five words break where a reader would."""
    lines = phrase_pages(_said("Margins fell again this quarter."),
                         max_words=4, max_chars=24, min_words=2)
    assert [" ".join(w.word for w in l) for l in lines] == \
        ["Margins fell", "again this quarter."]
    lines = phrase_pages(_said("A press release, not a purchase order."),
                         max_words=4, max_chars=24, min_words=2)
    assert [" ".join(w.word for w in l) for l in lines] == \
        ["A press release,", "not a purchase order."]


def test_the_long_keeps_the_lines_it_always_had(settings):
    """The LONG asks for no minimum and colours nothing, and gets exactly the
    walk it has always had: pinned against the pages the previous builder
    made of this text, at the defaults and at the LONG's own settings."""
    words = _said("The CEO cut his position by thirty-one percent on the first "
                  "of July. I'm not building a thesis on that, because people "
                  "sell stock for a hundred boring reasons. School fees. A divorce.")
    got = [" ".join(w.word for w in p) for p in phrase_pages(words)]
    assert got == ["The CEO cut his position", "by thirty-one percent on the first",
                   "of July.", "I'm not building a thesis",
                   "on that, because people sell stock",
                   "for a hundred boring reasons.", "School fees.", "A divorce."]
    got = [" ".join(w.word for w in p)
           for p in phrase_pages(words, max_words=8, max_chars=46)]
    assert got == ["The CEO cut his position by thirty-one percent",
                   "on the first of July.", "I'm not building a thesis on that,",
                   "because people sell stock for a hundred boring",
                   "reasons.", "School fees.", "A divorce."]

    ass = build_phrase_ass(words, settings=settings, play_res=(1920, 1080),
                           font_size=52, margin_v=120, margin_h=180,
                           max_words=8, max_chars=46, duration=30.0)
    assert "\\1c" not in ass
    assert all(f[7] == "0" for f in _dialogue(ass)), "a per-line margin"
    assert _style(ass)[5].strip().startswith("&H0A"), "the box's alpha moved"


# ---------------------------------------------------------------------------
# One term in colour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tokens, figures", [
    ("EXMPL is up twenty nine percent today,", ["twenty nine percent"]),
    ("on five times average volume,", ["five times"]),
    ("a hundred and sixty-two percent of what", ["a hundred and sixty-two percent"]),
    ("minus twenty-four million", ["minus twenty-four million"]),
    ("revenue of $4.2bn, up 12% and 40bps", ["$4.2bn,", "12%", "40bps"]),
    ("one of them, not one percent", ["one percent"]),
    ("the 10-Q in FY21 and Q3", []),
])
def test_a_figure_is_found_typed_or_spoken(tokens, figures):
    """The narration spells its numbers out for the voice, and the captions
    are the narration's words: a digits-only test would find nothing in a real
    script. A lone "one" is "one of them"; a filing's name is not a figure."""
    toks = tokens.split()
    assert [" ".join(toks[s:e]) for s, e, _ in figure_spans(toks)] == figures


@pytest.mark.parametrize("line, key", [
    ("not twenty nine percent", "twenty nine percent"),
    ("from four ninety six to four hundred million", "four hundred million"),
    ("A press release, not a purchase", "not"),
    ("The business isn't.", "isn't."),
    ("Cheap only counts", "only"),
    ("The chart went vertical.", None),
    ("but the business went sideways", None),
])
def test_the_key_is_the_figure_then_the_turn_word_then_nothing(line, key):
    """A figure wins, and of two the one carrying its unit. With none, the
    word that reverses or narrows the line. "But" is not one: it says a turn is
    coming, and the turn is the words after it."""
    toks = line.split()
    span = key_span(toks)
    assert (" ".join(toks[span[0]:span[1]]) if span else None) == key


def test_no_caption_colours_more_than_one_term(settings):
    ass = build_phrase_ass(_short_words(settings), settings=settings,
                           play_res=SHORT_FRAME, max_words=4, min_words=2,
                           max_chars=24, key_words=True)
    lines = _dialogue(ass)
    coloured = [f for f in lines if _keys(f[9])]
    assert coloured and len(coloured) < len(lines)
    ink = _rgb(_style(ass)[3])
    for f in coloured:
        on, off = _keys(f[9])
        assert _rgb(off) == ink and _rgb(on) != ink, f[9]
    # The punctuation around a key stays in ink.
    assert any("{\\1c" in f[9] and "percent{\\1c" in f[9] for f in coloured)


@pytest.mark.parametrize("hour", ["night", "dusk"])
def test_the_key_word_reads_on_the_caption_box_at_either_hour(settings, hour):
    """The caption's box is the kit's paper at every hour, and the night hour's
    `attention` is a coral drawn for the dark wall: on the cream box it is
    about 2.3:1. The key is `attention` drawn for the box it sits on, and it
    reads at 4.5:1 or better whichever hour the episode is at."""
    with episode_hour(hour):
        reg = load_plates(settings.assets_dir)
        ass = build_phrase_ass(_said("up twenty nine percent today."),
                               settings=settings, play_res=SHORT_FRAME,
                               max_words=4, min_words=2, key_words=True)
    box = _rgb(_style(ass)[5])
    on = _rgb(_keys(_dialogue(ass)[0][9])[0])
    assert contrast(on, box) >= 4.5, (hour, on, box)
    assert on in {reg.at(h).colour("attention") for h in reg.hour_suffixes}


def test_the_episodes_own_attention_is_used_where_it_reads(monkeypatch, settings):
    """The fallback is for legibility, not a second opinion: where the
    episode's own `attention` reads on the box it is the one set, and where
    nothing reads the line stays in its ink."""
    import pipeline.plates as plates_mod

    class _Reg:
        def __init__(self, palettes, attention):
            self.palettes, self._attention = palettes, attention

        def colour(self, role):
            assert role == "attention"
            return self._attention

    paper = {"ground": "#F2E8D4", "structure": "#2A2036", "attention": "#A8243C"}
    wall = {"ground": "#171D2A", "structure": "#C6D2E0", "attention": "#F07A5A"}
    monkeypatch.setattr(plates_mod, "load_plates",
                        lambda _d: _Reg({"night": wall, "dusk": paper}, (0x1E, 0x5A, 0x32)))
    ass = build_phrase_ass(_said("up twenty nine percent today."), settings=settings,
                           play_res=SHORT_FRAME, min_words=2, key_words=True)
    assert _rgb(_keys(_dialogue(ass)[0][9])[0]) == (0x1E, 0x5A, 0x32)

    faint = {**paper, "attention": "#E8D8C8"}
    monkeypatch.setattr(plates_mod, "load_plates",
                        lambda _d: _Reg({"dusk": faint}, (0xE8, 0xD8, 0xC8)))
    ass = build_phrase_ass(_said("up twenty nine percent today."), settings=settings,
                           play_res=SHORT_FRAME, min_words=2, key_words=True)
    assert "\\1c" not in ass


# ---------------------------------------------------------------------------
# Each window carries its own place
# ---------------------------------------------------------------------------

def test_each_line_burns_where_its_window_says(settings):
    """A subtitle file has one style and the SHORT places a caption per shot,
    so the place travels with the window and becomes that line's MarginV —
    the distance to the foot of the TYPE, which sits the box's inset above the
    foot of the box the window names."""
    W, H = SHORT_FRAME
    ass = build_phrase_ass(_said("Cheap only counts. The chart went vertical.",
                                 step=0.5),
                           settings=settings, play_res=SHORT_FRAME,
                           max_words=4, min_words=2, duration=10.0,
                           windows=[(0.0, 1.5, 1560), (1.5, 10.0, 1200)])
    margins = [int(f[7]) for f in _dialogue(ass)]
    assert margins == [H - 1560 + CAPTION_BOX_PAD, H - 1200 + CAPTION_BOX_PAD]


def test_a_line_carried_across_a_cut_moves_with_the_cut(settings):
    """A line may run on across a cut between two captioned shots. If the
    next shot placed its caption elsewhere, the rest of the line is there:
    left where the last shot put it, it sits over what this one shows. The
    entry punch is the line arriving, so the carried half has none."""
    words = _said("not a purchase order.", start=3.6, step=0.2)
    ass = build_phrase_ass(words, settings=settings, play_res=SHORT_FRAME,
                           max_words=4, min_words=2, duration=20.0,
                           windows=[(0.0, 4.0, 1560), (4.0, 6.0, 1400)])
    got = [(f[1], f[2], f[7], "\\fscx92" in f[9]) for f in _dialogue(ass)]
    assert got == [("0:00:03.60", "0:00:04.00", "374", True),
                   ("0:00:04.00", "0:00:05.15", "534", False)]

    # Two touching windows placed alike are still one stretch and one event.
    ass = build_phrase_ass(words, settings=settings, play_res=SHORT_FRAME,
                           max_words=4, min_words=2, duration=20.0,
                           windows=[(0.0, 4.0, 1560), (4.0, 6.0, 1560)])
    assert [(f[1], f[2]) for f in _dialogue(ass)] == [("0:00:03.60", "0:00:05.15")]


def test_a_placed_caption_still_ends_where_its_shot_does(settings):
    """Bug 27 with places on the windows: "Cheap only counts…" held over the
    whole payoff, the one shot that asked for no captions."""
    words = [WordTimestamp(word=w, start=s, end=s + 0.25, char_start=0, char_end=0)
             for w, s in (("Cheap", 5.0), ("only", 5.3), ("counts.", 5.6),
                          ("Noise.", 12.5))]
    ass = build_phrase_ass(words, settings=settings, play_res=SHORT_FRAME,
                           max_words=4, min_words=2, duration=20.0,
                           windows=[(0.0, 4.0, 1560), (4.0, 6.0, 1560),
                                    (12.0, 20.0, 1500)])
    assert [f[2] for f in _dialogue(ass)] == ["0:00:06.00", "0:00:13.45"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_burned_box_ends_where_the_window_says(settings, tmp_path):
    """The whole placement rests on one number: the box's foot. Measured off
    a burned frame, with the kit's own face, key word and all."""
    import numpy as np
    from PIL import Image

    W, H = SHORT_FRAME
    font = int(H * CAPTION_TYPE_FH)
    ass_path = tmp_path / "c.ass"
    ass_path.write_text(build_phrase_ass(
        _said("up twenty nine percent today."), settings=settings,
        play_res=SHORT_FRAME, font_size=font, margin_h=int(W * CAPTION_SIDE_FW),
        max_words=4, min_words=2, key_words=True, punch=False, duration=3.0,
        windows=[(0.0, 3.0, 1560)]), encoding="utf-8")
    png = tmp_path / "c.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c=0x171D2A:s={W}x{H}:d=2",
                    "-vf", f"format=rgb24,ass='{ass_path}':"
                           f"fontsdir='{settings.fonts_dir}'",
                    "-ss", "0.5", "-frames:v", "1", str(png)], check=True)
    px = np.asarray(Image.open(png).convert("RGB")).astype(int)
    box = np.abs(px - np.array([0xF2, 0xE8, 0xD4])).sum(axis=2) < 40
    rows = np.where(box.any(axis=1))[0]
    assert (rows.min(), rows.max() + 1) == (1560 - caption_box_height(font), 1560)
    # One box, not two: a colour change draws no seam down the line. Read
    # in the inset above the type, where the box is all there is, and in
    # RGB, since 4:2:0 chroma would smear the box's own edge into it.
    top = int(rows.min()) + CAPTION_BOX_PAD // 2
    row = px[top, np.where(box[top])[0]]
    assert len({tuple(p) for p in row}) == 1


# ---------------------------------------------------------------------------
# Placing the caption on the shot
# ---------------------------------------------------------------------------

class _Stub:
    """Fills every slot the shorts ask for, with values of the right shape."""

    def text_for(self, src: str) -> str | None:
        parts = set(src.split("."))
        if {"series", "figures"} & parts:
            return ",".join(str(10 + i * 3) for i in range(6))
        if {"heads", "axis"} & parts:
            return "a,b,c,d"
        if "years" in parts:
            return "a,b,c,d,e,f"
        leaf = src.rsplit(".", 1)[-1]
        # A figure under a bar is what the bar is drawn from.
        if leaf.startswith("value-"):
            return "12.5"
        if leaf in ("versus", "reported", "expected", "latest", "label",
                    "headline_figure", "headline_label", "headline_kicker",
                    "last", "unit", "ticker", "kicker", "expected_label"):
            return "vs" if leaf == "versus" else "3.4%"
        return f"words for {leaf}"

    def image_for(self, src: str):
        # The company's picture (item 34) is a required slot on the second
        # beat of every vertical cut.
        return Path(f"{src}.png") if src.startswith("photo.") else None

    def list_for(self, src: str):
        return None


@pytest.fixture(scope="module")
def reg():
    from config import Settings
    return load_plates(Settings(_env_file=None).assets_dir)


def _build(reg, name: str, seed: str):
    fmt = expand_sequences(load_format(name), lambda src: ["m1", "m2", "m3", "m4"])
    words = [WordTimestamp(word=f"w{i}", start=i * 70 / 240,
                           end=(i + 1) * 70 / 240, char_start=0, char_end=0)
             for i in range(240)]
    spans = resolve_spans(fmt, words, 70.0, {})
    return build_layers(fmt, spans, _Stub(), reg, aspect=fmt.aspect, seed=seed)


def _band_for(reg, result, shot_id: str, box_h: int,
              name: str = "") -> tuple[int, int]:
    """The band a caption may sit in: the plate's own, inside the clear area
    the format declares (item 27), where it declares one."""
    plate = next((reg.get(l.entry_key) for l in result.for_shot(shot_id)
                  if l.kind == "plate"), None)
    safe = getattr(load_format(name), "safe", None) if name else None
    return caption_band(plate, result.frame, box_h, safe=safe)


CUTS = [(name, seed) for name in ("short", "earnings", "macro")
        for seed in ("test", "b", "c")]


@pytest.mark.parametrize("name, seed", CUTS)
def test_every_caption_sits_inside_the_band_the_phone_leaves_clear(reg, name, seed):
    """The old band ran from 78% to 92% of the frame, and the caption's box
    burned at 1600-1684 of 1920: under the title, the channel name and the
    buttons on every shot of every short."""
    result = _build(reg, name, seed)
    caps = result.of_kind("caption")
    assert caps
    for l in caps:
        top, bottom = _band_for(reg, result, l.shot_id, l.h, name)
        assert top <= l.y and l.y + l.h <= bottom, (l.shot_id, l.y, l.h)
        assert l.h == caption_box_height(int(result.frame[1] * CAPTION_TYPE_FH))


@pytest.mark.parametrize("name, seed", CUTS)
def test_a_caption_covers_nothing_where_anywhere_is_free_and_least_where_not(
        reg, name, seed):
    """Checked against every row of the band, not against the placement's own
    shortlist of candidates: the covered area first, then how far inside the
    clearance, then the lowest. A caption over a filled slot is only ever the
    best a crowded shot allows."""
    import numpy as np

    result = _build(reg, name, seed)
    fw, fh = result.frame
    side = int(fw * CAPTION_SIDE_FW)
    pad = int(round(fh * CAPTION_CLEARANCE_FH))
    for cap in result.of_kind("caption"):
        obstacles = caption_obstacles(reg, result.for_shot(cap.shot_id))
        top, bottom = _band_for(reg, result, cap.shot_id, cap.h, name)

        def profile(grow: int):
            mask = np.zeros((fh, fw - 2 * side), dtype=bool)
            for _, (ox, oy, ow, oh) in obstacles:
                x0, x1 = max(ox, side) - side, min(ox + ow, fw - side) - side
                y0, y1 = max(oy - grow, 0), min(oy + oh + grow, fh)
                if x1 > x0 and y1 > y0 and oh > 0:
                    mask[y0:y1, x0:x1] = True
            return np.concatenate([[0], np.cumsum(mask.sum(axis=1))])

        hard, near = profile(0), profile(pad)

        def cost(y):
            return (hard[y + cap.h] - hard[y], near[y + cap.h] - near[y], -y)

        best = min(cost(y) for y in range(top, bottom - cap.h + 1))
        assert cost(cap.y) == best, (cap.shot_id, cap.y, best)


def test_the_lowest_clear_place_wins():
    """Low is where a caption is looked for, so it goes as low as the band
    and the shot allow, the clearance kept off the figure below it."""
    box_h = caption_box_height(57)
    pad = int(round(1920 * CAPTION_CLEARANCE_FH))
    y, covers = place_caption((260, 1560), [("row-3", (80, 1300, 900, 400))],
                              SHORT_FRAME, box_h)
    assert (y, covers) == (1300 - pad - box_h, [])
    y, covers = place_caption((260, 1560), [], SHORT_FRAME, box_h)
    assert (y, covers) == (1560 - box_h, [])
    # Outside the caption's width is not in its way.
    y, _ = place_caption((260, 1560), [("rail", (0, 1300, 60, 400))],
                         SHORT_FRAME, box_h)
    assert y == 1560 - box_h


def test_nowhere_clear_covers_least_and_names_what(reg, caplog):
    """A dense chart fills the band from its top to its period labels. The
    caption goes where it hides least, and the render says so, naming what
    it covers."""
    box_h = caption_box_height(57)
    y, covers = place_caption(
        (260, 1560), [("plot-area", (150, 300, 840, 1180)),
                      ("period-labels", (108, 1490, 864, 70))],
        SHORT_FRAME, box_h)
    # Over the labels it would hide all of them and a sliver of plot; at the
    # top it hides the top of the plot and nothing else.
    assert (y, covers) == (260, ["plot-area"])

    with caplog.at_level(logging.WARNING, logger="pipeline.compose"):
        _build(reg, "short", "test")
    said = [r.getMessage() for r in caplog.records if "covers least" in r.getMessage()]
    assert any(m.startswith("the-move:") and "plot-area" in m for m in said), said


def test_a_caption_never_covers_the_hosts_head(reg):
    """The turn is told to camera in close-up, and his face is the shot. The
    framing publishes its own head box; a standing figure's head is the top
    of him."""
    for name, seed in CUTS:
        result = _build(reg, name, seed)
        for cap in result.of_kind("caption"):
            for what, (x, y, w, h) in caption_obstacles(
                    reg, result.for_shot(cap.shot_id)):
                if what == "the host's head":
                    assert cap.y >= y + h or cap.y + cap.h <= y, (name, cap.shot_id)

    box_h = caption_box_height(57)
    y, covers = place_caption((260, 1560), [("the host's head", (200, 1250, 680, 310))],
                              SHORT_FRAME, box_h)
    assert covers == [] and y + box_h <= 1250


def test_a_plates_own_safe_band_is_the_one_used(reg):
    """Design's shorts plates publish the band themselves, in canvas units.
    It is the PLATFORM's band at the plate's size, so it maps by the canvas
    height, never through a push-in."""
    plate = reg.get("shorts/short-chart-9x16")
    assert plate.safe.get("top") == 260 and plate.safe.get("bottom") == 1560
    own = replace(plate, safe={"top": 300, "bottom": 1400})
    assert caption_band(own, SHORT_FRAME, 85) == (300, 1400)
    assert caption_band(own, (540, 960), 43) == (150, 700)
    assert caption_band(None, SHORT_FRAME, 85) == (
        round(CAPTION_BAND[0] * 1920), round(CAPTION_BAND[1] * 1920)) == (260, 1560)


def test_a_landscape_caption_stays_where_it_always_was(settings):
    """No phone lays buttons over a long's frame, and the long's captions are
    not this item's: a 16:9 cut through this engine gets one place, and the
    line burns at exactly the margin it always had."""
    W, H = 1920, 1080
    box_h = caption_box_height(int(H * CAPTION_TYPE_FH))
    top, bottom = caption_band(None, (W, H), box_h)
    assert bottom - top == box_h
    y, covers = place_caption((top, bottom), [("plot-area", (0, 0, W, H))],
                              (W, H), box_h)
    assert (y, covers) == (top, [])
    ass = build_phrase_ass(_said("the chart went vertical."), settings=settings,
                           play_res=(W, H), windows=[(0.0, 5.0, bottom)])
    assert int(_dialogue(ass)[0][7]) == int(H * 0.13)


def test_a_shot_without_captions_still_gets_none(reg):
    """`captions: false` (the hook card, the payoff's big number) and a plate
    setting display type both still mean no caption layer at all."""
    for name, seed in CUTS:
        result = _build(reg, name, seed)
        for span in result.spans:
            has = any(l.kind == "caption" for l in result.for_shot(span.shot.id))
            if not span.shot.captions or span.shot.has_large_type:
                assert not has, (name, span.shot.id)
        off = [sp.shot.id for sp in result.spans if not sp.shot.captions]
        assert off, name


def test_placement_is_deterministic(reg):
    a = [(l.shot_id, l.y) for l in _build(reg, "short", "b").of_kind("caption")]
    b = [(l.shot_id, l.y) for l in _build(reg, "short", "b").of_kind("caption")]
    assert a == b


# ---------------------------------------------------------------------------
# The render reads what the layers placed
# ---------------------------------------------------------------------------

def test_the_render_burns_each_caption_where_its_shot_placed_it(
        settings, tmp_path, short_valid_json, monkeypatch):
    """The whole path, frames stubbed: the caption layers `build_layers`
    placed are the windows the ASS gets, every line sits at its own shot's
    place and inside no captions-off shot, and the burn is given the kit's
    fonts — without them libass set every caption in DejaVu Sans."""
    import pipeline.render_short as rs
    from pipeline.parser_short import parse_short_script
    from pipeline.tts import TTSEngine

    built = {}

    def keep(*a, **k):
        built["result"] = result = build_layers(*a, **k)
        return result

    def frames(result, resolver, duration, out, settings, **_):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c=black:s=108x192:d={duration:.3f}:r=5",
                        "-pix_fmt", "yuv420p", str(out)], check=True)
        return out

    burns = []

    def burn(args):
        burns.append(args)
        shutil.copy(args[1], args[-1])

    monkeypatch.setattr(rs, "build_layers", keep)
    monkeypatch.setattr(rs, "render_frames", frames)
    monkeypatch.setattr(rs, "held_over_ceiling", lambda *a, **k: [])
    monkeypatch.setattr(rs, "run_ffmpeg", burn)

    script, _ = parse_short_script(short_valid_json, settings=settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, fmt="short",
                                         free_only=True)
    rs.render_short(script, tts, tmp_path, settings, proof=True)

    result = built["result"]
    W, H = result.frame
    caps = result.of_kind("caption")
    ass = (tmp_path / "render_short" / "captions.ass").read_text(encoding="utf-8")
    lines = _dialogue(ass)
    assert lines and caps

    def secs(t: str) -> float:
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    for f in lines:
        start, end, mv = secs(f[1]), secs(f[2]), int(f[7])
        # By the middle of the line: ASS times are centiseconds, and a line
        # split at a cut at 7.172 s starts at "7.17", before the cut.
        mid = (start + end) / 2
        home = next(l for l in caps if l.t_start <= mid < l.t_end)
        assert mv == H - (home.y + home.h) + CAPTION_BOX_PAD, (f, home.name)
        assert end <= home.t_end + 0.01 or any(
            abs(l.t_start - home.t_end) < 1e-6 for l in caps), f
        assert len(_keys(f[9])) in (0, 2), f[9]
    for span in result.spans:
        if not span.shot.captions:
            assert not any(secs(f[1]) < span.end - 0.01 and secs(f[2]) > span.start + 0.01
                           for f in lines), span.shot.id

    (args,) = burns
    vf = args[args.index("-vf") + 1]
    assert "fontsdir=" in vf and str(settings.fonts_dir).replace(":", "\\:") in vf
