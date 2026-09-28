"""What the kit does not draw: captions, alpha clips, and annotation marks.

Everything with a plate equivalent has gone. This module existed because the
renderer had to draw what the kit did not ship — sheets, cards, panels, chapter
stingers, backdrops — and the kit now ships all of it. What is left is the work
that is genuinely not a plate:

* **captions** (`build_phrase_ass`, `phrase_pages`) — ASS subtitles, which are
  a text format rather than a drawing
* **alpha clips** (`frames_to_alpha_clip`) — the encode step every animated
  overlay goes through
* **annotation marks** (`fitted_mark`, `mark_frames`) — solving an
  `annotations/` cut-out onto a target and drawing it on
* **small utilities** (`simple_text`, `drawn_rect`, `cover_fill_frame`)

A number counting up is `pipeline.moves`' count-up, on design's frames.

THERE ARE NO COLOUR CONSTANTS HERE ANY MORE. `INK`, `RED`, `GREEN`, `PANEL` and
`CARD_LINE` named a palette that no longer exists, and worse, `RED` carried both
"this went down" and "look at this" — so nothing on screen could tell the two
apart. Colour is asked for by ROLE through the registry
(`pipeline.plates.Registry.colour`): ground, second-ground, structure, down, up,
neutral-data, attention, other-party. Red means down. Emphasis is attention.
"""

from __future__ import annotations

import logging
import math
import random
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from config import Settings
from pipeline.models import WordTimestamp
from pipeline.render_common import run_ffmpeg

log = logging.getLogger(__name__)

# The two faces the kit ships, and the only two anything here may set. Every
# plate's typeRoles names one of them; a third face in a caption is a third
# voice on screen.
ARCHIVO = "ArchivoNarrow[wght].ttf"
COURIER = "CourierPrime-Regular.ttf"
COURIER_BOLD = "CourierPrime-Bold.ttf"


def role(settings: Settings, name: str) -> tuple[int, int, int]:
    """A palette colour, BY ROLE, off the registry.

    The one way anything in this module gets a colour. There is no hex here to
    go stale, and no name that means two things: ``down`` is a fall, and
    emphasis is ``attention``.
    """
    from pipeline.plates import load_plates

    return load_plates(settings.assets_dir).colour(name)


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def luminance(c: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB colour."""
    def lin(v: int) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def caption_colours(settings: Settings) -> tuple[tuple[int, int, int],
                                                 tuple[int, int, int]]:
    """The captions' ink and box: the kit's ink on the kit's paper, AS A PAIR.

    Design decided captions are a different register from the plates — the
    kit's materials without its hand, dark ink in a box of the kit's paper
    (kit/CHANGES.md, "Captions: deliberately a different register"). The first
    cut asked for `structure` at the base hour and put it on a cream box
    typed out here as a hex. That held while the base hour was the paper one.
    The rebuild's base hour is night, where `structure` is the pale ink drawn
    for a dark wall, and every caption came out pale on cream: about 1.3:1,
    unreadable, on every beat of every video.

    So both colours now come from ONE hour's palette — the hour whose ground
    is the lightest, which is the kit's paper — and can never be drawn for two
    different grounds. On a kit with a single dark hour this is light ink in
    a dark box, which is still the kit's own pairing and still legible.
    """
    from pipeline.plates import load_plates

    paper = _paper_palette(load_plates(settings.assets_dir))
    return _rgb(paper["structure"]), _rgb(paper["ground"])


def _paper_palette(reg) -> dict[str, str]:
    """The palette of the hour whose ground is the lightest: the kit's paper."""
    return max(reg.palettes.values(), key=lambda p: luminance(_rgb(p["ground"])))


# A key word has to read on the caption's box at least as well as the rest of
# the caption does: `test_captions_are_legible_on_their_own_box` holds the
# caption's own ink to 4.5:1, and a coloured word that is harder to read than
# the words around it has made the one word that matters the faint one.
CAPTION_KEY_CONTRAST = 4.5


def caption_key_colour(settings: Settings) -> tuple[int, int, int] | None:
    """The ink a caption's key word is set in: `attention`, drawn for the box.

    The episode's own `attention` when it reads on the caption's box, and
    otherwise `attention` from the hour whose paper the box IS. The box is the
    kit's paper at every hour (`caption_colours`), and the night hour's
    `attention` is a coral drawn for the dark wall: on the cream box it is
    about 2.3:1, the pale-ink-on-cream failure the night-legibility fix
    removed, back one word at a time. The paper hour's `attention` was drawn
    for exactly this ground. At dusk the two are the same colour.

    None when neither reads on the box, and the key word then stays in the
    caption's ink: an emphasis nobody can read is worse than none.
    """
    from pipeline.plates import load_plates

    reg = load_plates(settings.assets_dir)
    _, box = caption_colours(settings)
    for ink in (reg.colour("attention"), _rgb(_paper_palette(reg)["attention"])):
        if contrast(ink, box) >= CAPTION_KEY_CONTRAST:
            return ink
    return None


def load_font(settings: Settings, name: str, size: int,
              weight: int | None = None) -> ImageFont.FreeTypeFont:
    """A kit face at `size`, and at `weight` on the variable one.

    Archivo Narrow ships as one variable file whose default instance is 400,
    so a bold role asks for 700 here the way `plate_frames` sets it for a slot.
    The Courier Prime files are static and ignore `weight`.
    """
    font = ImageFont.truetype(str(settings.fonts_dir / name), size)
    if weight is not None and name == ARCHIVO:
        try:
            font.set_variation_by_axes([max(400, min(int(weight), 700))])
        except Exception:          # a FreeType without variable support
            log.debug("no variable-font support; %s stays at 400", name)
    return font


def simple_text(
    settings: Settings,
    text: str,
    *,
    font_name: str = COURIER_BOLD,
    font_size: int = 44,
    fill=None,
    stroke_width: int = 0,
    stroke_fill=None,
) -> Image.Image:
    fill = fill if fill is not None else (*role(settings, "structure"), 255)
    stroke_fill = (stroke_fill if stroke_fill is not None
                   else (*role(settings, "ground"), 255))
    font = load_font(settings, font_name, font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    w = int(probe.textlength(text, font=font)) + 2 * stroke_width + 8
    ascent, descent = font.getmetrics()
    h = ascent + descent + 2 * stroke_width + 6
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((stroke_width + 4, stroke_width + 2), text, font=font, fill=fill,
           stroke_width=stroke_width, stroke_fill=stroke_fill)
    return img
def _cover(img: Image.Image, W: int, H: int) -> Image.Image:
    """Scale + centre-crop `img` to exactly WxH (cover fit, no bars)."""
    scale = max(W / img.width, H / img.height)
    bw, bh = max(int(img.width * scale), W), max(int(img.height * scale), H)
    resized = img.resize((bw, bh), Image.LANCZOS)
    ox, oy = (bw - W) // 2, (bh - H) // 2
    return resized.crop((ox, oy, ox + W, oy + H))


def cover_fill_frame(
    src,
    width: int,
    height: int,
    *,
    ground: tuple[int, int, int],
    line: tuple[int, int, int],
    keep_min: float = 0.72,
    blur: int = 26,
    darken: float = 0.5,
    border: bool = True,
) -> Image.Image:
    """One media still, composed to fill a WxH frame in the Dennis look.

    If the media's aspect is close enough to the target that a cover-crop
    keeps at least `keep_min` of it, the media fills the frame edge-to-edge
    (real photos become the background). Otherwise — logos, tall phone
    grabs, panoramas — the media is CONTAINed sharp over a blurred, darkened,
    brand-tinted cover of itself, so it still reads as a designed full-frame
    shot and never a letterboxed black frame.
    """
    img = (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGB")
    W, H = width, height
    src_ar, dst_ar = img.width / img.height, W / H
    kept = min(src_ar / dst_ar, dst_ar / src_ar)  # fraction of area cover keeps
    if kept >= keep_min:
        return _cover(img, W, H)

    bg = ImageEnhance.Brightness(_cover(img, W, H).filter(
        ImageFilter.GaussianBlur(blur))).enhance(darken)
    bg = Image.blend(bg, Image.new("RGB", (W, H), ground), 0.42)
    fg = img.copy()
    fg.thumbnail((int(W * 0.92), int(H * 0.9)), Image.LANCZOS)
    ox, oy = (W - fg.width) // 2, (H - fg.height) // 2
    bg.paste(fg, (ox, oy))
    if border:
        ImageDraw.Draw(bg).rectangle(
            [ox - 2, oy - 2, ox + fg.width + 1, oy + fg.height + 1],
            outline=line, width=2)
    return bg


def frames_to_alpha_clip(frames: list[Image.Image], fps: int, out_path: Path) -> Path:
    """Encode RGBA frames once into a PNG-codec .mov (alpha preserved)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="frames_") as td:
        for i, frame in enumerate(frames):
            frame.save(Path(td) / f"f_{i:05d}.png")
        run_ffmpeg([
            "-framerate", str(fps),
            "-i", str(Path(td) / "f_%05d.png"),
            "-c:v", "png", "-pix_fmt", "rgba", str(out_path),
        ])
    return out_path


def held_frames_to_alpha_clip(frames: list[tuple[Image.Image, float]],
                              out_path: Path, *, fps: int = 12) -> Path:
    """As `frames_to_alpha_clip`, but each frame is held for its own time.

    For a clip that mostly stands still: a plate whose moves land seconds
    apart is the same picture for most of its twelve frames a second, and
    every one of them written out is a full PNG. Here a picture that holds is
    stored once, with how long it holds. Times are on the `fps` grid; each
    image is read at that rate, or the demuxer's default 25 would round every
    twelfth of a second to a multiple of 0.04.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="held_") as td:
        lines = ["ffconcat version 1.0"]
        last = None
        for i, (frame, seconds) in enumerate(frames):
            last = Path(td) / f"f_{i:05d}.png"
            frame.save(last)
            lines += [f"file '{last.name}'", f"option framerate {fps}",
                      f"duration {max(seconds, 1e-3):.6f}"]
        if last is None:
            raise ValueError("no frames to encode")
        # The concat demuxer only honours the last duration when the last
        # file is named once more after it; that adds one frame of the last
        # picture, which is the landed state and harmless.
        lines += [f"file '{last.name}'", f"option framerate {fps}"]
        listing = Path(td) / "frames.ffconcat"
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-fps_mode", "vfr", "-c:v", "png", "-pix_fmt", "rgba", str(out_path),
        ])
    return out_path


# --------------------------------------------------------------------------
# Captions (libass burns these in), phrase by phrase, driven by the real audio
# timestamps. Not karaoke: see `build_phrase_ass`.
# --------------------------------------------------------------------------


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"
# Where a caption line may end: on punctuation, not mid-clause.
_PHRASE_END = re.compile(r"[.!?…]$|[,;:—–]$")

# Function words a line must never end on: a caption ending "of" or "the"
# leaves the eye hanging for a frame and a half.
_NEVER_LAST = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "from", "with", "by", "as", "is", "was", "are", "were", "that", "which",
    "than", "into", "over", "its", "it's", "their", "your", "our", "his",
}

# How far the caption's box reaches past its line of type, in script pixels:
# the style's `Outline`, which under `BorderStyle 3` is the box's inset rather
# than a stroke. Named because the SHORT places the BOX, not the type. What
# covers a figure is the cream rectangle, and a placement that positioned the
# type would land the box fourteen pixels lower than it asked for.
CAPTION_BOX_PAD = 14


def caption_box_height(font_size: int) -> int:
    """How tall one caption's box is on screen, in script pixels.

    libass sets a line at exactly its font size (measured: a 57-pixel line
    burns an 85-pixel box) and the box adds its inset above and below. One
    line only, because the style sets `WrapStyle 2` and a caption never wraps.
    """
    return int(font_size) + 2 * CAPTION_BOX_PAD


# --------------------------------------------------------------------------
# Key words.
#
# A FIGURE IS WHATEVER THE CAPTION SHOWS, AND THE CAPTION SHOWS WHAT WAS SAID.
# The narration spells its numbers out for the voice, "twenty nine percent"
# and "four ninety six" (`pipeline/spoken.py`), and a caption is the
# narration's own words. So a figure on screen is almost always a run of
# number words, and a digits-only test would colour nothing in a real script.
# Both forms count: a typed token (29%, $4.2bn, 5×, 40bps) and a spoken run
# with whatever unit is said after it.
# --------------------------------------------------------------------------

_NUMERALS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion", "trillion",
})
_BIG_SCALES = frozenset({"thousand", "million", "billion", "trillion"})

# Said after a figure, and part of it: "five TIMES", "forty BASIS POINTS".
_UNIT_WORDS = frozenset({"percent", "times", "dollars", "dollar", "cents",
                         "pounds", "pence", "euros", "points", "bps"})
_UNIT_PAIRS = frozenset({("per", "cent"), ("basis", "points"),
                         ("percentage", "points")})

# A figure as it is typed: a sign, a currency, digits, and the units the
# channel writes. 29%, -$15M, $4.2bn, 5×, 3x, 40bps, 2.5pt.
_TYPED_FIGURE = re.compile(
    r"[+\-−]?[$£€]?\d[\d,]*(?:\.\d+)?(?:%|×|x|bn|b|m|k|t|bps|pts?)?", re.I)

# A token with its punctuation off. Quotes, brackets and clause marks go; a
# sign, a currency and a trailing % or × stay, because those are the figure.
_CORE = re.compile(r"^[^\w$£€+\-−]*(.*?)[^\w%×]*$", re.S)

# A word that ends a clause ends a figure with it: "twenty nine percent," and
# the "four" that opens the next clause are two figures, not one.
_RUN_ENDS = re.compile(r"[.,;:!?…—–)\]\"”’]$")

# THE KEY WORD WHEN THERE IS NO FIGURE: a word that reverses or narrows what
# the line says. A caption is read in a glance, and "The business is not."
# read without its "not" is the opposite sentence. Contractions ("isn't") are
# the same word. "But" is left out on purpose: it says a turn is coming, and
# the turn is the words after it. So is everything else, because colour on
# every other line stops meaning "look here", which is all `attention` is for.
_TURN_WORDS = frozenset({"not", "no", "never", "only"})


def _core(token: str) -> str:
    m = _CORE.match(token.strip())
    return (m.group(1) if m else token.strip()).lower()


def _is_numeral(core: str) -> bool:
    return bool(core) and all(p in _NUMERALS for p in core.split("-"))


def _unit_end(cores: list[str], tokens: Sequence[str], j: int) -> int:
    """Past the unit said at `j`, straight after a figure, if one is."""
    if (j + 1 < len(cores) and (cores[j], cores[j + 1]) in _UNIT_PAIRS
            and not _RUN_ENDS.search(tokens[j].strip())):
        return j + 2
    if j < len(cores) and cores[j] in _UNIT_WORDS:
        return j + 1
    return j


def figure_spans(tokens: Sequence[str]) -> list[tuple[int, int, bool]]:
    """Where the figures are in a run of caption words: `(start, end, marked)`.

    `end` is exclusive and takes in the unit said after the figure. `marked`
    is a figure that carries its unit (a percent, a currency, a multiple, a
    scale), which is what tells "four hundred million" apart from the "six"
    in "six years". A lone "one" is not a figure: it is "one of them" far
    more often than it is a number.
    """
    cores = [_core(t) for t in tokens]
    ends = [bool(_RUN_ENDS.search(t.strip())) for t in tokens]
    n = len(tokens)
    out: list[tuple[int, int, bool]] = []
    i = 0
    while i < n:
        c = cores[i]
        if c and _TYPED_FIGURE.fullmatch(c):
            end = i + 1 if ends[i] else _unit_end(cores, tokens, i + 1)
            # A sign is a unit too: "+29" is a move, where "29" is a count.
            bare = c.replace(",", "").replace(".", "").isdigit()
            out.append((i, end, end > i + 1 or not bare))
            i = end
            continue
        # A spoken run: a sign or an "a hundred", then numerals, with "and" and
        # "point" taken only where a numeral follows them.
        k = i
        if c in ("minus", "negative", "a"):
            nxt = cores[i + 1] if i + 1 < n and not ends[i] else ""
            wanted = (nxt in _BIG_SCALES or nxt == "hundred") if c == "a" \
                else _is_numeral(nxt)
            if not wanted:
                i += 1
                continue
            k = i + 1
        count = 0
        while k < n:
            if _is_numeral(cores[k]):
                count += 1
                k += 1
                if ends[k - 1]:
                    break
            elif (count and not ends[k] and cores[k] in ("and", "point")
                  and k + 1 < n and _is_numeral(cores[k + 1])):
                k += 1
            else:
                break
        if not count:
            i += 1
            continue
        end = k if ends[k - 1] else _unit_end(cores, tokens, k)
        said = {p for w in cores[i:k] for p in w.split("-")}
        marked = end > k or c in ("minus", "negative") or bool(said & _BIG_SCALES)
        if not marked and cores[i:k] == ["one"]:
            i = k
            continue
        out.append((i, end, marked))
        i = end
    return out


def key_span(tokens: Sequence[str]) -> tuple[int, int] | None:
    """The one term a caption line sets in `attention`, as `(start, end)`.

    A figure wins, and of two figures the first that carries its unit. With no
    figure, the first turn word (`_TURN_WORDS`). Never more than one: two
    coloured words in a four-word line is a line with no emphasis at all. A
    figure said in four words is still one term, coloured whole, because half
    a number in colour reads as a different number.
    """
    figures = figure_spans(tokens)
    if figures:
        s, e, _ = next((f for f in figures if f[2]), figures[0])
        return s, e
    for i, t in enumerate(tokens):
        c = _core(t).replace("’", "'")
        if c in _TURN_WORDS or c.endswith("n't"):
            return i, i + 1
    return None


def _keyed(tokens: Sequence[str], on: str, off: str) -> str:
    """The line as ASS text, its key term in the `on` colour, if it has one.

    The punctuation around the term stays in the line's ink: a comma in the
    key colour reads as a stray mark beside the word rather than part of it.
    """
    parts = list(tokens)
    span = key_span(parts)
    if span is None:
        return " ".join(parts)
    s, e = span
    lead = re.match(r"[\"'“‘(\[]*", parts[s]).group(0)
    trail = re.search(r"[.,;:!?…—–)\]\"'”’]*$", parts[e - 1]).group(0)
    first = parts[s][len(lead):]
    if s == e - 1:
        body = first[:len(first) - len(trail)] if trail else first
        if not body:
            return " ".join(parts)
        parts[s] = f"{lead}{{\\1c{on}}}{body}{{\\1c{off}}}{trail}"
    else:
        last = parts[e - 1][:len(parts[e - 1]) - len(trail)] if trail else parts[e - 1]
        parts[s] = f"{lead}{{\\1c{on}}}{first}"
        parts[e - 1] = f"{last}{{\\1c{off}}}{trail}"
    return " ".join(parts)


def phrase_pages(
    words: list[WordTimestamp],
    *,
    max_words: int = 6,
    max_chars: int = 30,
    max_gap: float = 0.45,
    min_words: int = 1,
) -> list[list[WordTimestamp]]:
    """Group words into caption lines that break on phrase boundaries.

    Three things end a line, in priority order: sentence-final punctuation, a
    real pause in the delivery, and clause punctuation once the line is long
    enough to be worth breaking. The length caps are a backstop, and when one
    fires it walks back off a function word rather than stranding it.

    `min_words` above one asks for lines of `min_words` to `max_words`, which
    this walk cannot give: it only learns a line was short after it has ended
    it. Those lines are chosen a sentence at a time instead
    (`_balanced_pages`). The LONG asks for no minimum and gets this walk,
    exactly as before.
    """
    if min_words > 1:
        return _balanced_pages(words, min_words=min_words, max_words=max_words,
                               max_chars=max_chars, max_gap=max_gap)
    pages: list[list[WordTimestamp]] = []
    page: list[WordTimestamp] = []

    def flush() -> None:
        nonlocal page
        if page:
            pages.append(page)
            page = []

    for i, w in enumerate(words):
        page.append(w)
        text = w.word.strip()
        n_chars = sum(len(x.word) + 1 for x in page) - 1
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt else 0.0

        hard = bool(re.search(r"[.!?…]$", text))
        soft = bool(_PHRASE_END.search(text)) and len(page) >= 3
        paused = nxt is not None and gap >= max_gap and len(page) >= 2
        full = len(page) >= max_words or n_chars >= max_chars

        if hard or soft or paused:
            flush()
        elif full:
            # Walk back off a dangling function word so the break lands
            # somewhere a reader would have paused anyway.
            if len(page) > 2 and page[-1].word.strip(".,;:!?").lower() in _NEVER_LAST:
                carry = page.pop()
                flush()
                page = [carry]
            else:
                flush()
    flush()
    return pages


def _balanced_pages(words: list[WordTimestamp], *, min_words: int,
                    max_words: int, max_chars: int,
                    max_gap: float) -> list[list[WordTimestamp]]:
    """Lines of `min_words` to `max_words`, every break in a sentence at once.

    Four-and-flush does "Margins fell again this / quarter." to a five-word
    sentence. This scores every way of breaking the sentence and keeps the
    cheapest (`_line_cost`): three or four words to a line, a break on a
    clause mark or a pause where there is one, never on a function word, and
    never inside a figure, the one term in the sentence that has to arrive
    whole. A figure counts as ONE word however many it is said in, as it would
    if it were typed 29% rather than spoken. A sentence shorter than the
    minimum ("Noise.") is a line of its own, because joining it to the next
    one would caption across a full stop.
    """
    tokens = [w.word for w in words]
    figures = {(s, e) for s, e, _ in figure_spans(tokens)}
    pages: list[list[WordTimestamp]] = []
    start = 0
    for i, w in enumerate(words):
        if i + 1 < len(words) and not re.search(r"[.!?…]$", w.word.strip()):
            continue
        a, b = start, i + 1
        best = [0.0] + [math.inf] * (b - a)
        back = [a] * (b - a + 1)
        for end in range(a + 1, b + 1):
            for cut in range(a, end):
                if best[cut - a] == math.inf:
                    continue
                cost = best[cut - a] + _line_cost(
                    words, cut, end, last=end == b, figures=figures,
                    min_words=min_words, max_words=max_words,
                    max_chars=max_chars, max_gap=max_gap)
                if cost < best[end - a]:
                    best[end - a], back[end - a] = cost, cut
        lines: list[list[WordTimestamp]] = []
        end = b
        while end > a:
            cut = back[end - a]
            lines.append(words[cut:end])
            end = cut
        pages += reversed(lines)
        start = b
    return pages


def _line_cost(words: list[WordTimestamp], j: int, i: int, *, last: bool,
               figures: set[tuple[int, int]], min_words: int, max_words: int,
               max_chars: int, max_gap: float) -> float:
    """What it costs to make `words[j:i]` one caption line. Lower is better.

    The weights are ordered, not tuned: cutting a figure in two outweighs
    everything, a line over the cap outweighs a line under the minimum, a
    one-word line outweighs a function word at the end, and a clause mark or
    a pause at the break only ever decides between lines that are otherwise
    both fine.
    """
    whole = (j, i) in figures
    said = (i - j) - sum(e - s - 1 for s, e in figures if j <= s and e <= i)
    cost = 0.25 if whole else (said - 3.5) ** 2
    if said < min_words:
        cost += 20.0
    if said > max_words:
        cost += 50.0 * (said - max_words)
    chars = sum(len(w.word) for w in words[j:i]) + (i - j) - 1
    if chars > max_chars and not whole:
        cost += 0.5 * (chars - max_chars)
    if any(s < i < e for s, e in figures):
        cost += 100.0
    if not last:
        end = words[i - 1].word.strip()
        if end.strip(".,;:!?").lower() in _NEVER_LAST:
            cost += 8.0
        if _PHRASE_END.search(end):
            cost -= 3.0
        if words[i].start - words[i - 1].end >= max_gap:
            cost -= 3.0
    return cost


def build_phrase_ass(
    words: list[WordTimestamp],
    *,
    settings: Settings,
    play_res: tuple[int, int],
    font_size: int = 62,
    margin_v: int = 300,
    margin_h: int = 70,
    max_words: int = 6,
    max_chars: int = 30,
    min_words: int = 1,
    key_words: bool = False,
    duration: float | None = None,
    punch: bool = True,
    windows: Sequence[tuple[float, float] | tuple[float, float, int | None]]
    | None = None,
) -> str:
    """The captions: structure ink on the ground, phrase by phrase.

    Not karaoke. The word-by-word red fill was doing two things at once —
    colouring text in the same red that means a down-move, and drawing the eye
    along a line that had already been split mid-clause. This is one legible
    phrase at a time, in the same ink as everything else on the frame.

    `punch` gives each line a 60ms scale-up on entry. It is the caption half of
    the motion layer: enough to register as a cut, not enough to bounce.

    `windows` are the stretches captions may show in, when not all of the cut
    carries them. A line holds until the next one starts, and across a shot
    with captions off that is the whole shot: "Cheap only counts…" stayed up
    for seven seconds over the payoff card, the one shot that asked for none.
    Each line now also ends where its window does.

    A window may carry a third value: the y, in script pixels, where the
    caption's BOX ends while that window is on screen. The SHORT places its
    caption per shot, clear of what that shot is showing, and a subtitle file
    has one style, so the place travels with the window and becomes each
    line's own MarginV. A line that runs on across a cut into a window placed
    somewhere else is split at the cut and moves with it: the picture changes
    there anyway, and a caption left where the last shot put it sits over
    whatever this one is showing.

    `min_words` above one balances the lines (`phrase_pages`), and `key_words`
    sets one term a line in `attention` (`key_span`, `caption_key_colour`).
    Both are the SHORT's. The LONG passes neither, and its lines are exactly
    what they were.
    """
    W, H = play_res

    def bgr(c, alpha: int = 0):  # ASS colours are &HAABBGGRR
        r, g, b = c
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    def rgb_tag(c) -> str:       # an override colour is &HBBGGRR&
        r, g, b = c
        return f"&H{b:02X}{g:02X}{r:02X}&"

    ink, box = caption_colours(settings)
    key = caption_key_colour(settings) if key_words else None
    # AN OPAQUE BOX UNDER A COLOURED WORD. libass draws a `BorderStyle 3` box
    # per run of type, and a colour change starts a new run: the two boxes
    # overlap by the width of a space, and at the style's 4% transparency the
    # overlap is drawn twice, a pale seam down every line with a key word in
    # it. Opaque, the overlap cannot show. Lines with no colour keep the box
    # they have always had.
    box_alpha = 0x00 if key is not None else 0x0A

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caps,Archivo Narrow,{font_size},{bgr(ink)},{bgr(ink)},{bgr(box, box_alpha)},{bgr(box, box_alpha)},-1,0,0,0,100,100,0,0,3,{CAPTION_BOX_PAD},0,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Touching windows are one stretch: a line may run on across a cut
    # between two captioned shots, just not into a shot without captions.
    # Two touching windows placed differently stay two, and a line crossing
    # from one to the other is split where they meet. A MarginV of 0 is the
    # style's own, which is what a window with no place of its own gets.
    merged: list[list] = []
    for a, b, bottom in sorted(((float(w[0]), float(w[1]),
                                 w[2] if len(w) > 2 else None)
                                for w in (windows or ())),
                               key=lambda w: (w[0], w[1])):
        mv = 0 if bottom is None else max(int(H - bottom + CAPTION_BOX_PAD), 1)
        if merged and a <= merged[-1][1] + 1e-6 and merged[-1][2] == mv:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b, mv])

    events: list[str] = []
    pages = phrase_pages(words, max_words=max_words, max_chars=max_chars,
                         min_words=min_words)
    for i, page in enumerate(pages):
        start = page[0].start
        if i + 1 < len(pages):
            end = max(pages[i + 1][0].start, page[-1].end)
        else:
            end = page[-1].end + 0.7
        if duration is not None:
            end = min(end, duration)
        tokens = [w.word for w in page]
        text = (_keyed(tokens, rgb_tag(key), rgb_tag(ink)) if key is not None
                else " ".join(tokens))
        prefix = "{\\fscx92\\fscy92\\t(0,60,\\fscx100\\fscy100)}" if punch else ""
        for n, (a, b, mv) in enumerate(_through_windows(start, end, merged)):
            if b <= a:
                continue
            # The entry punch is the line ARRIVING. The rest of a line carried
            # across a cut is the same line, and a second punch would read as
            # a new caption with the same words.
            events.append(
                f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Caps,,0,0,{mv},,"
                f"{prefix if n == 0 else ''}{text}")
    return header + "\n".join(events) + "\n"


def _through_windows(start: float, end: float,
                     merged: list[list]) -> list[tuple[float, float, int]]:
    """A line's stretch on screen, cut where its windows change: `(a, b, mv)`.

    A line starting in no window runs as it always has, at the style's margin.
    """
    at = next((k for k, (a, b, _) in enumerate(merged) if a <= start < b), None)
    if at is None:
        return [(start, end, 0)]
    out: list[tuple[float, float, int]] = []
    a = start
    while True:
        _, b, mv = merged[at]
        out.append((a, min(end, b), mv))
        nxt = merged[at + 1] if at + 1 < len(merged) else None
        if end <= b + 1e-9 or nxt is None or nxt[0] > b + 1e-6:
            return out
        a, at = b, at + 1


# --------------------------------------------------------------------------
# Motion layer.
#
# Every one of these takes a finished still and returns the frames that bring
# it on. They are deliberately transforms rather than bespoke animations: the
# artwork is already drawn, and the motion is how it ARRIVES. Nothing here
# pans or zooms a held frame — the movement is entry only, and then it stops.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# The drawn primitives.
#
# The kit is a pen on paper: every border in it is a stroke, not a geometric
# rule. These live here rather than in `chart.py` because every module now
# draws with them — both charts, the thumbnail, and every card in this file —
# and a card that frames itself with `rounded_rectangle` is advertising a
# different product from the one it is part of.
# --------------------------------------------------------------------------


def marker_stroke(d, pts, rng, *, width, color, jitter, passes=2):
    """A marker line: the polyline drawn a few times with per-point jitter
    and a chunky nib — the crude hand-drawn look."""
    for _ in range(passes):
        wobbled = [(x + rng.uniform(-jitter, jitter),
                    y + rng.uniform(-jitter, jitter)) for x, y in pts]
        d.line(wobbled, fill=color, width=width, joint="curve")


def drawn_rect(d, box, rng, *, width, color, jitter=1.6, passes=1,
                overshoot=0.0):
    """A rectangle drawn by hand: four strokes, not a rounded_rectangle.

    `overshoot` runs each stroke past its corner by that fraction of the side,
    the way a pen does when you do not lift it — which is what stops four
    jittered lines from reading as a rectangle with bad anti-aliasing.
    """
    x0, y0, x1, y1 = box
    ox, oy = (x1 - x0) * overshoot, (y1 - y0) * overshoot
    for a, b in (((x0 - ox, y0), (x1 + ox, y0)),
                 ((x1, y0 - oy), (x1, y1 + oy)),
                 ((x1 + ox, y1), (x0 - ox, y1)),
                 ((x0, y1 + oy), (x0, y0 - oy))):
        marker_stroke(d, [a, b], rng, width=width, color=color,
                       jitter=jitter, passes=passes)
# A mark's nib, in delivered pixels. A plate downscaled onto a small target
# loses its stroke before it loses its shape, so the alpha is grown back to a
# floor — otherwise a tight oval around one cell arrives as a grey smudge.
MARK_NIB_PX = 11
MARK_MIN_NIB_PX = 5


# An annotation's style IS its plate name. The old table mapped twelve invented
# style words onto the retired `marks/` family; there is nothing left to map,
# because `[SCRIBBLE: strike-out -> …]` resolves to `annotations/strike-out`.
# `pipeline.models.SCRIBBLE_ALIASES` catches what a writer is likely to type
# instead ("circle", "underline") so a beat is never lost over a synonym.
#
# The second element is the procedural stroke drawn when the plate cannot be
# loaded. Decoration is never allowed to fail a render.
SCRIBBLE_MARKS: dict[str, tuple[str, str]] = {
    "scrawl-oval-wide": ("annotations/scrawl-oval-wide", "circle"),
    "scrawl-oval-tight": ("annotations/scrawl-oval-tight", "circle"),
    "underline-swipe": ("annotations/underline-swipe", "underline"),
    "underline-tight": ("annotations/underline-tight", "underline"),
    "strike-out": ("annotations/strike-out", "cross-out"),
    "box-scrawl": ("annotations/box-scrawl", "box"),
    "bracket-rows": ("annotations/bracket-rows", "bracket"),
    "arrow-elbow": ("annotations/arrow-elbow", "arrow"),
    "caret-note": ("annotations/caret-note", "caret"),
    "tick-marks": ("annotations/tick-marks", "check"),
}

# The legible band for a solved mark's stroke, in canvas units. The kit warns
# when `inkWeight x solve` leaves it: below, the mark is a hairline nobody sees;
# above, it is a smear over the thing it was meant to point at.
#
# SOLVE SCALE IS NOT THE METRIC. A tight mark reads fine at 0.4x and a wide mark
# at 0.4x is a hairline — the first version of this check compared scale alone
# and told the operator to use the tight mark they were already using.
INK_WEIGHT_BAND = (3.2, 26.0)


def mark_image(settings: Settings, key: str) -> Image.Image | None:
    """Frame one of an `annotations/` plate, or None.

    Never raises: a caller that cannot find its mark draws one rather than
    failing to render, which is the only sane failure mode for decoration.
    """
    try:
        from pipeline.plates import load_plates

        plate = load_plates(settings.assets_dir).get(key)
        if plate is None or not plate.frames:
            return None
        return Image.open(plate.frame_paths()[0]).convert("RGBA")
    except Exception:  # noqa: BLE001 — decoration is never fatal
        log.debug("no %s in the kit — the mark will be drawn instead", key)
        return None


def thicken_mark(img: Image.Image, radius: int) -> Image.Image:
    """Grow a mark's alpha, so a downscaled stroke keeps a legible nib."""
    if radius <= 0:
        return img
    a = img.getchannel("A").filter(ImageFilter.MaxFilter(2 * radius + 1))
    out = img.copy()
    out.putalpha(a)
    return out


def tint_mark(img: Image.Image, color) -> Image.Image:
    solid = Image.new("RGBA", img.size, (*color[:3], 0))
    solid.putalpha(img.getchannel("A"))
    return solid


def _same_gesture(style: str) -> list[str]:
    """Every mark drawn with the same gesture, the named one first.

    The table already says which those are: the second element is the stroke,
    so `scrawl-oval-wide` and `scrawl-oval-tight` are both "circle" and
    `underline-swipe` and `underline-tight` are both "underline". Reading the
    family off it rather than listing pairs means a mark the kit adds later
    joins its own family with no edit here.
    """
    gesture = SCRIBBLE_MARKS.get(style, ("", ""))[1]
    if not gesture:
        return [style]
    return [style] + sorted(s for s, (_k, g) in SCRIBBLE_MARKS.items()
                            if g == gesture and s != style)


def _solved_stroke(plate, target_w: int) -> float:
    """The stroke this mark lands at around a target `target_w` wide."""
    area = plate.slot("area") if plate is not None else None
    if area is None or not plate.ink_weight:
        return 0.0
    return plate.ink_weight * (target_w / max(area.w, 1))


def _pick_variant(reg, style: str, target_w: int) -> tuple[str, str]:
    """(style to draw, why it changed). THE MARK FITS THE TARGET.

    A wide oval is drawn to circle a line of type and a tight one to circle
    one word; asked to circle a four-character cell, the wide one solves to a
    stroke a third of the way below the legible band and arrives as a
    hairline. That is not a rendering problem and it is not the nib — it is
    the wrong mark, and which one is right is decided by how wide the thing
    being marked actually is.

    Only within a gesture. A bracket that groups rows and an oval around a
    word are different statements, and swapping one for the other because the
    arithmetic prefers it would be this code overruling the director rather
    than fitting what they asked for.
    """
    lo, hi = INK_WEIGHT_BAND
    candidates = []
    for name in _same_gesture(style):
        plate = reg.get(SCRIBBLE_MARKS.get(name, ("", ""))[0])
        if plate is None:
            continue
        candidates.append((name, _solved_stroke(plate, target_w)))
    if not candidates:
        return style, ""
    named, solved = candidates[0]
    if not solved or lo <= solved <= hi:
        return named, ""
    for name, other in candidates[1:]:
        if lo <= other <= hi:
            return name, (f"{named} solves to {solved:.1f} against a legible "
                          f"band of {lo}-{hi} on a target {target_w}px wide; "
                          f"{name} is the same gesture at {other:.1f}")
    return named, ""


def solve_mark(settings: Settings, style: str, target: tuple[int, int, int, int],
               *, report: dict | None = None
               ) -> tuple[tuple[int, int, int, int], list[str]] | None:
    """Where an annotation goes, given the box it wraps. Returns (box, warnings).

    THE MARK GOES ON THE TYPE, NOT ON THE SLOT RECTANGLE. A table cell is 216
    canvas units tall for 30-unit figures; an oval stretched onto the rectangle
    is an oval around empty space. Each mark declares an `area` slot — "what
    this wraps" — and the transform that lands `area` on the target is what puts
    the ink where it was drawn to fall. That is also what makes
    `underline-swipe` work with no special case: its swipe is drawn BELOW its
    area slot, so solving the area onto the word puts the swipe under the word.

    How a mark may be solved is declared, not assumed:

    * ``both``       x and y independently. Only safe for marks that ENCLOSE —
                     an oval is meant to take its target's proportions.
    * ``x-uniform``  fit the width, same scale for y. A line of its own natural
                     thickness stretched independently in y becomes a fat wave.

    and those carry an anchor: ``bottom`` for underlines, whose ink sits below
    the area slot, ``middle`` for strikes.
    """
    from pipeline.plates import load_plates

    if style not in SCRIBBLE_MARKS:
        return None
    reg = load_plates(settings.assets_dir)
    style, swapped = _pick_variant(reg, style, target[2])
    if report is not None:
        report["style"] = style
        if swapped:
            report["swapped"] = swapped
    plate = reg.get(SCRIBBLE_MARKS[style][0])
    if plate is None:
        return None
    area = plate.slot("area")
    if area is None:
        return None

    tx, ty, tw, th = target
    sx = tw / max(area.w, 1)
    sy = th / max(area.h, 1)
    if (plate.solve or "both") != "both":
        sy = sx                      # x-uniform: one scale, both axes

    warnings: list[str] = []
    if plate.ink_weight:
        solved = plate.ink_weight * sx
        lo, hi = INK_WEIGHT_BAND
        if solved > hi:
            warnings.append(
                f"{style} solves to a {solved:.1f}-unit stroke against a legible "
                f"band of {lo}–{hi} — a smear over what it points at. Mark the "
                f"figure rather than the sentence, or use the tight mark.")
        elif solved < lo:
            # Below the floor the advice is NOT "use the wide mark" — this is
            # usually already the wide one, and what shrank it is the target:
            # a single figure, or a plate scaled into a two-shot's evidence
            # column. Naming the cause is the difference between a warning an
            # operator can act on and one they learn to scroll past.
            warnings.append(
                f"{style} solves to a {solved:.1f}-unit stroke against a legible "
                f"band of {lo}–{hi} — the target is small enough that the mark "
                f"arrives as a hairline. Mark a wider target, or give the beat "
                f"the full frame.")

    # Place the whole plate so its area slot lands on the target.
    w = int(round(plate.canvas[0] * sx))
    h = int(round(plate.canvas[1] * sy))
    x = int(round(tx - area.x * sx))
    y = int(round(ty - area.y * sy))
    if plate.anchor == "bottom":
        y = int(round(ty + th - (area.y + area.h) * sy))
    elif plate.anchor == "middle":
        y = int(round(ty + th / 2 - (area.y + area.h / 2) * sy))

    # A MARK DRAWS OUTSIDE WHAT IT WRAPS. A target so wide that the solved
    # canvas leaves the frame cannot be circled at all — the fix is to circle
    # the figure rather than the sentence, and saying so is more use than
    # silently drawing two arcs off the edge.
    return (x, y, w, h), warnings


def fitted_mark(settings: Settings, w: int, h: int, *, style: str,
                color=None) -> Image.Image | None:
    """An annotation plate scaled into a w x h box, tinted, or None."""
    key = SCRIBBLE_MARKS.get(style, ("", ""))[0]
    if not key:
        return None
    mark = mark_image(settings, key)
    if mark is None:
        return None
    scale = min(w / mark.width, h / mark.height)
    mw, mh = max(int(mark.width * scale), 1), max(int(mark.height * scale), 1)
    mark = mark.resize((mw, mh), Image.LANCZOS)
    mark = thicken_mark(
        mark, int(round((MARK_MIN_NIB_PX - MARK_NIB_PX * scale) / 2)))
    if color is not None:
        mark = tint_mark(mark, color)
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    plate.alpha_composite(mark, ((w - mw) // 2, (h - mh) // 2))
    return plate


def mark_frames(
    settings: Settings | None,
    w: int,
    h: int,
    *,
    style: str,
    color=None,
    fps: int = 30,
    draw_seconds: float = 0.4,
    stroke: int | None = None,
    seed: str = "mark",
) -> list[Image.Image]:
    """`style` drawing itself on — the kit's mark when one ships, else drawn.

    An annotation is drawn in ATTENTION, and that is the point: it SPENDS the
    frame's one attention, so a plate that already carries an attention mark
    cannot also be annotated.
    """
    if color is None:
        color = role(settings, "attention") if settings else (224, 160, 22)
    art = fitted_mark(settings, w, h, style=style, color=color) if settings else None
    n = max(int(draw_seconds * fps), 1)
    if art is not None:
        # Wipe the artwork on left to right, so it reads as being drawn.
        out = []
        for i in range(n):
            frac = _ease_out((i + 1) / n)
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            cut = max(int(w * frac), 1)
            frame.paste(art.crop((0, 0, cut, h)), (0, 0))
            out.append(frame)
        return out
    return _drawn_mark_frames(
        w, h, style=SCRIBBLE_MARKS.get(style, ("", "circle"))[1], color=color,
        fps=fps, draw_seconds=draw_seconds, stroke=stroke, seed=seed)


def _drawn_mark_frames(w: int, h: int, *, style: str, color, fps: int,
                       draw_seconds: float, stroke: int | None,
                       seed: str) -> list[Image.Image]:
    """The procedural fallback, for when the plate cannot be loaded.

    Deliberately crude. It is not trying to be the artwork — it is here so that
    a missing mark is a rougher mark rather than a missing beat, and so nothing
    in the annotation path can raise during a render.
    """
    rng = random.Random(seed)
    width = stroke or max(int(min(w, h) * 0.055), 3)
    cx, cy = w / 2, h / 2
    rx, ry = w * 0.46, h * 0.42

    def ellipse_pts(n: int = 44) -> list[tuple[float, float]]:
        return [(cx + rx * math.cos(2 * math.pi * i / n + 0.4),
                 cy + ry * math.sin(2 * math.pi * i / n + 0.4))
                for i in range(n + 3)]

    paths: list[list[tuple[float, float]]] = {
        "circle": [ellipse_pts()],
        "box": [[(w * .06, h * .1), (w * .94, h * .08), (w * .95, h * .9),
                 (w * .05, h * .92), (w * .06, h * .1)]],
        "underline": [[(w * .04, h * .74), (w * .96, h * .68)],
                      [(w * .08, h * .88), (w * .9, h * .84)]],
        "cross-out": [[(w * .06, h * .18), (w * .94, h * .84)],
                      [(w * .06, h * .84), (w * .94, h * .18)]],
        "bracket": [[(w * .72, h * .04), (w * .22, h * .1), (w * .2, h * .9),
                     (w * .7, h * .96)]],
        "arrow": [[(w * .05, h * .12), (w * .55, h * .2), (w * .9, h * .8)],
                  [(w * .78, h * .74), (w * .9, h * .8), (w * .76, h * .9)]],
        "caret": [[(w * .3, h * .9), (w * .5, h * .5), (w * .7, h * .9)]],
        "check": [[(w * .1, h * .55), (w * .3, h * .8), (w * .6, h * .2)]],
    }.get(style, [ellipse_pts()])

    total = sum(max(len(p) - 1, 1) for p in paths)
    n = max(int(draw_seconds * fps), 1)
    frames: list[Image.Image] = []
    for i in range(n):
        drawn = _ease_out((i + 1) / n) * total
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        budget = drawn
        for path in paths:
            take = int(min(max(budget, 0), len(path) - 1)) + 1
            if take >= 2:
                marker_stroke(d, path[:take], rng, width=width,
                              color=(*color[:3], 255), jitter=1.5)
            budget -= len(path) - 1
        frames.append(img)
    return frames


def _ease_out(t: float) -> float:
    """Fast, then settling. The house easing for anything that lands."""
    return 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** 3
