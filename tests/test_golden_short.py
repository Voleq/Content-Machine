"""The evidence test: render a hosted light-theme SHORT and LOOK at it.

The suite passed green while producing a video with no host, a mismatched
theme and inaudible audio. Every assertion in it was true — the filter graph
had the right arguments, the manifest had the right cue times, the layer names
were all present. None of that is evidence about what came out.

So this module asserts on the FRAMES and the WAVEFORM:

* the host is really drawn — measured against the bare backdrop in the band he
  occupies, not inferred from a layer name;
* the whole frame is the light kit, sampled across the runtime, so a dark
  chart or a dark closing card fails here rather than in an upload;
* the audio is audible and lands in the speech band, so the mock render that
  measured 0.0 LUFS and played as silence cannot come back;
* and the frames are compared against a stored golden set, so a layout that
  moves has to be looked at and re-blessed on purpose.

Bless with: DENNIS_BLESS_GOLDEN=1 pytest tests/test_golden_short.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from pipeline.byproducts import (
    bless,
    check_report,
    compare_against_golden,
    extract_frames,
    frame_distance,
    golden_dir,
)
from pipeline.models import CueKind
from pipeline.tts import TTSEngine

GOLDEN_NAME = "short_hosted"
ROOT = Path(__file__).resolve().parents[1]

# A hosted short exercising the whole grammar: bookends, two-shot returns,
# card tags that fall through to the blank layouts, played animations with
# slots, delivery direction, and the light payoff card.
#
# Deliberately loaded to sit INSIDE the 18-22-events-per-75s band. The first
# version of this fixture was thin enough to trip the "reads as a slideshow"
# warning, which meant the pacing contract had only ever been exercised from
# below — through the one path that renders it.
HOSTED_RAW = json.dumps({
    "ticker": "EXMPL",
    "format": "short",
    "hook_text": "EXMPL is up 29% today. The business is not.",
    "chart_style": "clean",
    "audio_script": (
        "EXMPL is up twenty nine percent today on five times average volume. "
        "[BEAT] The news is a partnership, which is a press release, [DRY] not "
        "a purchase order. [PROP: crushed-flat = -41%] No revenue attached to "
        "it anywhere. Plus a squeeze, because eleven percent of the float was "
        "short. [PROP: b-towering-chart = $1.1T] But here is the part nobody "
        "screenshots. [BEAT] Revenue went four hundred million to four ninety "
        "six in five years. That is a plateau in a costume. "
        "[TERM: owner earnings] Losses got "
        "[SCRIBBLE: circle -> Net income] wider every year. "
        "[PROP: numbers-raining = -8%, -12%, -3%, -21%, -6%, -15%, -9%] "
        "Free cash flow went negative and stayed "
        "there, which means you pay them to own it. "
        "[PROP: see-saw-two-numbers = heavy:$1.1B, light:$40M] "
        "The share count grows six percent a year, so your slice shrinks while "
        "you wait. [BIGNUM: dilution = 6% a year] I know a value trap; my own "
        "account went from twenty five k to zero. [SIGH] In fairness there is "
        "enough cash on the balance sheet to survive being wrong for a while. "
        "[PROP: umbrella-red-rain = -8%, -12%, -3%, $2.4B] Which is the nicest "
        "thing I can say, and I am reaching. [DOODLE: crash] The chart went "
        "vertical. The business went sideways. "
        "Noise. A press release and a squeeze, stapled to five years of drift."
    ),
    "move_summary": "+29% today · 5× average volume",
    "headlines": [
        {"text": "EXMPL announces AI partnership",
         "meaning": "A press release, not a purchase order."},
        {"text": "Squeeze chatter on retail forums",
         "meaning": "11% of the float is short."},
    ],
    "years": ["2021", "2022", "2023", "2024", "2025"],
    "numbers": [
        {"label": "Revenue", "values": ["$400M", "$452M", "$471M", "$491M", "$496M"]},
        {"label": "Net income", "values": ["-$8M", "-$25M", "-$49M", "-$70M", "-$89M"]},
        {"label": "Shares out", "values": ["298M", "315M", "330M", "346M", "365M"]},
    ],
    "numbers_comment": "Flat revenue, widening losses, a growing share count.",
    "cheap_or_trap": "Eleven times sales for a business that has not grown in three years.",
    "conclusion": "Noise. A press release and a squeeze, stapled to five years of drift.",
    "annotations": [
        {"target": "chart", "anchor_word": "today", "note": "this candle"},
        {"target": "numbers", "row_index": 1, "anchor_word": "wider", "note": "every year"},
    ],
})

# Sampled across the runtime rather than at the edges: a fade is the least
# informative frame in a video and the most likely to differ for uninteresting
# reasons.
SAMPLE_FRACTIONS = (0.03, 0.16, 0.34, 0.52, 0.70, 0.86, 0.97)

# The light kit is paper (#f2f2ef, luminance 242) with ink on it. A frame that
# means to be light still measures well above this once the type, the chart
# and the host line work are counted; the dark closing card measured 73.
LIGHT_FLOOR = 150.0


@pytest.fixture(scope="module")
def hosted(tmp_path_factory):
    from config import Settings

    from pipeline.parser_short import parse_short_script
    from pipeline.render_short import render_short

    tmp = tmp_path_factory.mktemp("golden_short")
    settings = Settings(
        MOCK_MODE=True,
        workspace_dir=tmp / "ws",
        cache_dir=tmp / "cache",
        state_dir=tmp / "state",
        short_width=540,
        short_height=960,
        _env_file=None,
    )
    settings.ensure_runtime_dirs()
    script, warnings = parse_short_script(HOSTED_RAW, settings)
    tts = TTSEngine(settings).synthesize(script.audio_script, "short",
                                         events=script.inline_events)
    ws = settings.workspace_dir / "EXMPL" / "golden"
    ws.mkdir(parents=True)
    out, manifest_path = render_short(script, tts, ws, settings)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    frames_dir = tmp / "frames"
    times = [round(tts.duration_s * f, 2) for f in SAMPLE_FRACTIONS]
    frames = extract_frames(out, frames_dir, at=times, settings=settings)
    return settings, script, tts, out, manifest, frames, warnings


def _mean_luminance(path: Path) -> float:
    img = Image.open(path).convert("RGB")
    img.thumbnail((160, 160))
    px = list(img.getdata())
    return sum((r * 299 + g * 587 + b * 114) // 1000 for r, g, b in px) / len(px)


def _audio_stat(video: Path, filt: str, key: str) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", filt, "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    for line in reversed(proc.stderr.splitlines()):
        if key in line:
            token = line.split(key, 1)[1].strip().split()[0]
            return float(token.rstrip("dB").rstrip("LUFS").strip())
    raise AssertionError(f"{key} not reported by ffmpeg for {video}")


# --------------------------------------------------------------------------
# The host is on screen.
# --------------------------------------------------------------------------


def test_the_host_is_actually_drawn_not_just_declared(hosted):
    """Pixel evidence, not a layer name.

    The engine this replaced emitted HOST_OPEN and HOST_CLOSE cues, carried a
    host module, and drew no host at all — every name-based assertion in the
    suite passed. So: crop the band Dennis occupies out of a real frame from
    the opening beat and compare it with the bare backdrop. If he is there,
    the two are nothing alike.
    """
    settings, script, tts, out, manifest, frames, _ = hosted
    from pipeline.kit import load_kit
    from pipeline.render_short import BACKDROP_KEY, HOST_Y

    assert manifest["host"]["shots"] >= 2, "bookends need at least two shots"

    W, H = settings.short_resolution
    scale = W / 1080.0
    band = (0, int(HOST_Y * scale), W, min(int((HOST_Y + 600) * scale), H))

    kit = load_kit(settings.assets_dir)
    backdrop = Image.open(kit.require(BACKDROP_KEY).path).convert("RGB")
    backdrop = backdrop.resize((W, H)).crop(band)

    host_cue = next(c for c in manifest["cues"] if c["kind"] == "host_open")
    t = (host_cue["t"] + float(host_cue["payload"]["until"])) / 2
    shot_dir = out.parent / "hostcheck"
    shot = extract_frames(out, shot_dir, at=[round(t, 2)], settings=settings)[0]
    frame = Image.open(shot).convert("RGB").crop(band)

    a, b = shot_dir / "a.png", shot_dir / "b.png"
    frame.save(a)
    backdrop.save(b)
    distance = frame_distance(a, b)
    assert distance > 20.0, (
        f"the host band at t={t:.1f}s is indistinguishable from the bare "
        f"backdrop (Δ{distance:.1f}) — nothing was drawn there")


def test_the_host_bookends_and_a_return_are_all_lip_synced(hosted):
    """Open, close, and a mid-video return, each from a real talk pair."""
    settings, script, tts, out, manifest, frames, _ = hosted
    names = {layer["name"] for layer in manifest["layers"]}
    assert {"host_open", "host_close"} <= names
    assert any(n.startswith("host_beat") for n in names), \
        "Dennis never comes back mid-video"

    from pipeline.host import HOST_BANKS, pick_shot
    from pipeline.kit import load_kit

    kit = load_kit(settings.assets_dir)
    for role in HOST_BANKS:
        shot = pick_shot(kit, role, 0)
        assert shot is not None, f"no usable talk pair for the {role!r} bank"
        assert shot.closed.key != shot.open_.key


# --------------------------------------------------------------------------
# The theme.
# --------------------------------------------------------------------------


def test_every_sampled_frame_is_the_light_kit(hosted):
    """One theme, end to end.

    The cards were inverted when the palette flipped and the backdrop, the
    napkin chart and the closing cards were not, so a short opened on paper
    and closed on near-black. Sampling the whole runtime is what catches that:
    the failure was always in the last five seconds.
    """
    settings, script, tts, out, manifest, frames, _ = hosted
    assert manifest["theme"] == "light"
    dark = [(f.name, round(_mean_luminance(f), 1)) for f in frames
            if _mean_luminance(f) < LIGHT_FLOOR]
    assert not dark, f"frames below the light floor ({LIGHT_FLOOR}): {dark}"


def test_the_payoff_card_is_light_too(hosted):
    """The card that closes every video, checked as artwork rather than as a
    layer name — it was one of the seven dark ones."""
    settings, script, tts, out, manifest, frames, _ = hosted
    from scripts.restyle_dark_cards import DARK_CARDS, KIT, mean_luminance

    for key in DARK_CARDS:
        registry = json.loads((KIT / "kit-registry.json").read_text(encoding="utf-8"))
        entry = registry["assets"][key]
        base = KIT / "shorts" if entry["source"] == "shorts" else KIT
        for frame in entry["frames"]:
            lum = mean_luminance(base / frame)
            assert lum >= 128, f"{key} is still dark ({lum:.0f})"


# --------------------------------------------------------------------------
# The audio.
# --------------------------------------------------------------------------


def test_the_render_is_audible_and_in_the_speech_band(hosted):
    """The silent-render bug, asserted on the waveform.

    A mock render measured 0.0 LUFS integrated with a -0.9 dB peak and played
    as silence: the placeholder was a 155 Hz hum, `loudnorm` measured a
    near-silent programme and raised it about thirty decibels, and the gain
    went into the limiter as inaudible sub-bass. Three things have to hold now
    — real loudness, no clipping, and energy where a voice lives.
    """
    settings, script, tts, out, manifest, frames, _ = hosted
    lufs = _audio_stat(out, "ebur128=peak=true", "I:")
    peak = _audio_stat(out, "ebur128=peak=true", "Peak:")
    full = _audio_stat(out, "volumedetect", "mean_volume:")
    above_200 = _audio_stat(out, "highpass=f=200,volumedetect", "mean_volume:")

    assert -34.0 < lufs < -8.0, f"integrated loudness is {lufs} LUFS"
    assert peak <= -0.5, f"true peak {peak} dBFS is clipping"
    # Sub-bass-only audio loses almost everything to the high-pass. A signal
    # that is genuinely in the speech band keeps most of its energy.
    assert full - above_200 < 12.0, (
        f"most of the energy is below 200 Hz (full {full} dB, "
        f"above 200 Hz {above_200} dB) — that is a hum, not speech")


def test_mock_audio_is_not_normalised(hosted):
    """Bypass, not tuning: `loudnorm` on a placeholder tone is what broke it."""
    settings, script, tts, out, manifest, frames, _ = hosted
    filter_text = (out.parent / (out.stem + ".filter.txt")).read_text(encoding="utf-8")
    assert "loudnorm" not in filter_text, \
        "mock audio went through loudnorm — that is the silent-render path"
    assert "alimiter" in filter_text, "the limiter must stay on either way"


# --------------------------------------------------------------------------
# The golden set.
# --------------------------------------------------------------------------


def test_frames_match_the_golden_set(hosted):
    """A layout change has to be looked at and re-blessed on purpose."""
    settings, script, tts, out, manifest, frames, _ = hosted
    if os.environ.get("DENNIS_BLESS_GOLDEN"):
        n = bless(frames, settings, GOLDEN_NAME)
        pytest.skip(f"blessed {n} golden frame(s) for {GOLDEN_NAME}")

    ref = golden_dir(settings, GOLDEN_NAME)
    if not ref.is_dir():
        pytest.skip(f"no golden set at {ref} — bless with "
                    f"DENNIS_BLESS_GOLDEN=1")
    diffs = compare_against_golden(frames, settings, GOLDEN_NAME)
    assert diffs, "golden set exists but nothing was compared"
    assert all(d.ok for d in diffs), check_report(diffs)


def test_the_cut_is_paced_inside_the_band(hosted):
    """A properly loaded short produces no pacing complaint at all.

    The band is a target, not a direction. Asserting the clean case is what
    keeps the rule honest — a contract only ever checked against a cut that
    violates it has never been shown to pass.
    """
    settings, script, tts, out, manifest, frames, warnings = hosted
    assert manifest["pacing_warnings"] == [], manifest["pacing_warnings"]


def test_data_beats_hold_and_punctuation_does_not(hosted):
    """The two classes, measured on the cues that actually reached the cut."""
    from pipeline.timeline import SHORT_DATA_HOLD_S, SHORT_PUNCT_HOLD_S

    settings, script, tts, out, manifest, frames, warnings = hosted
    seen = {"data": 0, "punct": 0}
    for cue in manifest["cues"]:
        klass = cue["payload"].get("class")
        if klass not in seen:
            continue
        seen[klass] += 1
        hold = float(cue["payload"]["hold"])
        lo, hi = SHORT_DATA_HOLD_S if klass == "data" else SHORT_PUNCT_HOLD_S
        assert lo <= hold <= hi, f"{cue['payload'].get('tag')} held {hold}s"
    assert seen["data"] and seen["punct"], \
        f"the fixture must exercise both classes: {seen}"


def test_the_tag_grammar_reached_the_frame(hosted):
    """The short can address the library now — asserted on what it used.

    The floor is the acceptance bar for the rebuild: the version this replaced
    passed every other test in this file while reaching six assets. A short
    that draws on fewer than fifteen is back to being a slideshow with one
    drawing in it, whatever the rest of the suite says.
    """
    settings, script, tts, out, manifest, frames, warnings = hosted
    used = set(manifest["kit_assets_used"])
    assert "shorts/dennis-vs-numbers/numbers-raining" in used, \
        "a slotted, animated shorts asset should have played"
    assert "blanks/term-card-blank" in used, \
        "[TERM] with no named artwork should fall through to the blank layout"
    assert "blanks/big-number-blank" in used, \
        "[BIGNUM] should fall through to its blank layout the same way"
    assert "shorts/vertical-scenes/b-towering-chart" in used, \
        "a 9:16 scene should have replaced the frame rather than been boxed"
    assert any(k.startswith("shorts/the-world/") for k in used), \
        "the desk set should carry the acts"
    assert len(used) >= 15, f"only reached {len(used)} kit assets: {sorted(used)}"


def test_every_beat_reports_how_much_of_the_frame_it_takes(hosted):
    """The number the layout exists to move, in the artefact that ships.

    "The frame reads empty" was an opinion until this was measured: the stage
    box was a 1000x760 landscape rectangle on a 1080x1920 frame, so a 1:1
    drawing covered 28% of the screen.
    """
    settings, script, tts, out, manifest, frames, warnings = hosted
    beats = manifest["beat_coverage"]
    assert beats, "no beat recorded its size"
    for b in beats:
        assert b["class"] in ("data", "punct")
        assert 0.0 < b["frac"] <= 1.0
        assert b["w"] > 0 and b["h"] > 0
    assert "median_data_coverage" in manifest
    assert "median_punct_coverage" in manifest


def test_a_plated_beat_reports_the_artwork_not_the_plate(hosted):
    """A card composed onto a full-frame plate owns the frame, but its
    typesetting still covers what it covers. Reporting the plate would make
    the measurement unfalsifiable."""
    settings, script, tts, out, manifest, frames, warnings = hosted
    for b in manifest["beat_coverage"]:
        if b.get("plated"):
            assert b["beat_frac"] > b["frac"], b
            assert b["frac"] < 1.0


def test_the_short_fills_the_frame_at_least_once(hosted):
    """Eleven drawings are 1080x1920 compositions — the only assets built to
    BE this frame — and they only fired when a writer named one by key."""
    settings, script, tts, out, manifest, frames, warnings = hosted
    assert any(b["frac"] >= 0.99 for b in manifest["beat_coverage"]), \
        "nothing filled the frame"


def test_square_artwork_is_no_longer_a_sticker(hosted):
    """Fitting a 1:1 drawing to the frame's width instead of into a landscape
    box takes it from 28% of frame to 56%."""
    settings, script, tts, out, manifest, frames, warnings = hosted
    square = [b for b in manifest["beat_coverage"] if abs(b["w"] - b["h"]) <= 2]
    if not square:
        pytest.skip("this script used no square artwork")
    assert min(b["frac"] for b in square) > 0.2, square


def test_the_room_carries_the_middle_of_the_video(hosted):
    """The gut check is the longest section and it played on blank paper —
    only the open, the chart and the payoff had a desk under them."""
    settings, script, tts, out, manifest, frames, warnings = hosted
    names = {l["name"] for l in manifest["layers"]}
    assert any(n.startswith("act_mid") for n in names), \
        "nothing was behind the evidence section"


def test_the_untagged_number_rows_reach_artwork_off_the_number(hosted):
    """Thirty-four drawings whose whole job is making a figure land, and they
    only ever appeared if the writer named one.

    A row the script did not tag picks one off the number itself — from the
    small `dennis-vs-numbers` batch, or from the full-frame vertical scenes,
    which are the same mechanism choosing the bigger register.
    """
    settings, script, tts, out, manifest, frames, warnings = hosted
    from pipeline.number_beats import NUMBER_BEATS
    from pipeline.vertical_beats import VERTICAL_BEATS

    banks = {k for keys in NUMBER_BEATS.values() for k in keys}
    banks |= {k for keys in VERTICAL_BEATS.values() for k in keys}
    tagged = {str(e.payload).lower() for e in script.inline_events}
    reached = {k for k in set(manifest["kit_assets_used"]) & banks
               if k.rsplit("/", 1)[-1].lower() not in tagged}
    assert reached, "no beat was reached for any untagged number row"


def test_the_hosts_own_card_does_not_bring_a_second_ticker(hosted):
    """The host shots are long-form chapter cards with a ticker chip painted
    into them. Left on, every short opens with a placeholder from the design
    file on screen next to ours."""
    settings, script, tts, out, manifest, frames, warnings = hosted
    from PIL import Image

    from pipeline.kit import load_kit
    from pipeline.kit_frames import strip_baked_furniture

    kit = load_kit(settings.assets_dir)
    for role_key in ("chapters/cold-open/at-desk-open",
                     "chapters/resigned-close/dennis-defeated"):
        asset = kit.get(role_key)
        if asset is None:
            continue
        src = Image.open(asset.frames[0]).convert("RGBA")
        assert strip_baked_furniture(src, asset) is not src, (
            f"{role_key} still carries its long-form furniture into the short")

    # delivery direction reaches the voice, never the screen
    from pipeline.models import DELIVERY_TAG_TYPES

    delivery = [e for e in script.inline_events if e.type in DELIVERY_TAG_TYPES]
    assert len(delivery) >= 3, "delivery tags were dropped by the parser again"
    for tag in ("[BEAT]", "[SIGH]", "[DRY]"):
        assert tag not in script.audio_script
