"""The prompt he pastes into Figma Make for the thumbnail (7 Nov 2026).

He makes the covers in Figma. The bot already writes the title and the
thumbnail's words (`pipeline.titles`), and draws its own cover from the
video's room; this turns all three into one prompt for Figma Make, shown at
the upload step, so the cover he makes is about the video the title sells
and in the channel's look: warm paper, ink type, one marker colour, Dennis
as he is in the video.

The colours are the kit's paper inks (`kit/design-tokens.json`,
`plateInk.paper`), read at run time so a kit that changes them changes the
prompt. The faces are the kit's two (`pipeline.rasters`).
"""

from __future__ import annotations

import json
from pathlib import Path

# The kit's paper inks when the token file cannot be read.
_FALLBACK_INK = {"ground": "#F4F2EA", "structure": "#0B0E16",
                 "subject": "#283C9A", "attention": "#B8262E",
                 "subject5": "#2E9152"}
_TOKENS = Path(__file__).resolve().parents[1] / "kit" / "design-tokens.json"

SIZES = {"long": (1280, 720), "short": (1080, 1920)}


def paper_ink() -> dict[str, str]:
    try:
        hours = json.loads(_TOKENS.read_text(encoding="utf-8"))["hours"]
        ink = next(iter(hours.values()))["plateInk"]["paper"]
        return {k: str(ink.get(k) or v) for k, v in _FALLBACK_INK.items()}
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return dict(_FALLBACK_INK)


def figma_make_prompt(*, fmt: str, ticker: str, title: str,
                      thumbnail_text: str = "", company: str = "",
                      figure: str = "", cover_name: str = "") -> str:
    """One prompt, ready to paste. `fmt` is "long" or "short" (a clip is
    cut from the long and gets the short's tall cover)."""
    tall = fmt != "long"
    w, h = SIZES["short" if tall else "long"]
    ink = paper_ink()
    ticker = (ticker or "").upper()
    from pipeline.implosions import code_word, is_story_code

    if is_story_code(ticker):
        # An implosion: a famous blow-up, under its story's name. Its code
        # (`IMP-KNIGHT12`) is the bot's filing label, never cover material.
        who = company or code_word(ticker).title()
        kind = "a dry, funny story of how " + who + " blew up"
    else:
        who = f"{company} ({ticker})" if company and company.upper() != ticker else ticker
        kind = ("a short (under a minute) on why " + who + " moved today"
                if tall else "a dry, funny deep dive on " + who)
    words = thumbnail_text.strip()
    cover = cover_name or ("the bot's tall cover" if tall else "the bot's cover")
    lines = [
        f"Design a YouTube {'Shorts cover' if tall else 'thumbnail'}: one frame, "
        f"{w} x {h} px ({'9:16' if tall else '16:9'}). Only the picture: no "
        f"browser, phone, YouTube page or buttons around it.",
        "",
        "THE VIDEO",
        f"“{title}”: {kind}, from Dennis, a 3D cartoon finance host.",
        "",
    ]
    if words:
        lines += [
            "THE WORDS (the biggest thing in the frame; exactly these, and "
            "nothing else in big type)",
            f"“{words.upper()}”",
            "One or two lines, each about a quarter of the frame's "
            f"{'width' if tall else 'height'}, readable on a phone at the size "
            "of a stamp. They add to the title, so don't put the title on it.",
        ]
    else:
        lines += [
            "THE WORDS",
            "Two to four words that add to the title (not the title itself), "
            "as the biggest thing in the frame.",
        ]
    if figure and not any(ch.isdigit() for ch in words):
        lines.append(f"Under them, smaller, in typewriter bold: “{figure}”. "
                     f"It is the video's own figure; don't change it.")
    lines += [
        "",
        "THE PICTURE",
        f"I've attached {cover}, from the upload page: Dennis in his room. "
        "Keep Dennis exactly as he is there: glasses, navy crew-neck, short "
        "beard and moustache. Cut him out and "
        + ("place him in the lower half, under the words, facing the viewer."
           if tall else "place him on the right third, turned toward the words.")
        + " Don't redraw him, restyle him, or make him look like a real person.",
        f"Behind everything: warm paper, {ink['ground']}, with a faint paper "
        "grain. No photo background, no gradient, no glow, no lens flare.",
        "",
        "TYPE AND COLOUR (the channel's look)",
        f"- Words: Archivo Narrow, Bold, in ink {ink['structure']}, tight "
        "leading, " + ("centred." if tall else "left-aligned."),
        "- Any figure: Courier Prime Bold.",
        f"- One accent at most: marker red {ink['attention']} for a number that "
        f"is bad, marker green {ink['subject5']} only for a rise, marker blue "
        f"{ink['subject']} for an underline or a circle. Everything else is ink.",
        "- Hand-drawn feel: one felt-pen underline, circle or arrow at most.",
        "",
        "LAYOUT",
    ]
    if tall:
        lines += [
            "- Words in the middle third of the height. Keep the top 15% and "
            "the bottom 20% clear: YouTube's buttons and caption sit there.",
            "- 60 px margin on the left and right.",
        ]
    else:
        lines += [
            "- Words on the left two thirds, Dennis on the right third.",
            "- Keep the bottom-right corner clear: YouTube puts the video's "
            "length there. 40 px margin on every edge.",
        ]
    lines += [
        "- Three things at most: the words, Dennis, and one figure or prop.",
        "",
        "DON'T",
        "- No buy or sell arrows, rockets, moons, money piles, price targets or "
        "\"BREAKING\" banners.",
        "- No company logo unless I attach one, and never an invented logo.",
        "- No other people's faces.",
        ("- No real person's face or likeness: the story's people are named, "
         "never drawn." if is_story_code(ticker) else
         f"- Don't make the ticker{f' ({ticker})' if ticker else ''} the big words."),
        "",
        f"Export a PNG, {w} x {h}, under 2 MB.",
    ]
    return "\n".join(lines)
