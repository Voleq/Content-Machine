"""The SHORT's one meme: picked from the owned library, placed, recorded.

Three layers of it, tested apart. The PICKER reads a script against the
library's tags and "use when" lines and answers with one meme or none. The
TEMPLATE says where a format may carry one. The COMPOSITOR overlays it on one
end of that shot's span, inside a frames/ plate, clear of the payoff's drop.
None of them may reach past the library: a short never fetches a meme.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pipeline import memes
from pipeline.compose import (MEME_HOLD_S, MEME_SHARE, MEME_SRC, _meme_frame,
                              _slot_in_frame, _fit, build_layers,
                              check_invariants, meme_window, payoff_guards,
                              placed_meme)
from pipeline.media_frames import MEDIA_TREATMENTS
from pipeline.memes import (MEME_FLOOR, MemeLibrary, choose_for_short,
                            memes_in_manifest, recent_memes)
from pipeline.shots import TemplateError, load_format, parse_format, resolve_spans
from pipeline.sound import DROP_S, PAYOFF_SHOTS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _library(tmp_path: Path, entries: dict) -> MemeLibrary:
    """A library of plain stills: `{stem: (index entry, (w, h))}`."""
    d = tmp_path / "meme_library"
    d.mkdir(exist_ok=True)
    index = {}
    for stem, (entry, size) in entries.items():
        Image.new("RGB", size, (220, 220, 220)).save(d / f"{stem}.png")
        index[stem] = entry
    (d / "meme_index.json").write_text(json.dumps(index), encoding="utf-8")
    return MemeLibrary(settings=None, library_dir=d)


BEAT_SOLD_OFF = SimpleNamespace(
    hook_text="They beat every estimate and the stock fell eight percent.",
    verdict="Beat, and it did not matter.")


def _script(name: str, settings):
    from pipeline.parser_short import parse_short_script

    script, _ = parse_short_script(
        (FIXTURES / f"{name}.json").read_text(encoding="utf-8"),
        settings=settings)
    return script


def _manifest(settings, ticker: str, day: str, payload: dict,
              name: str = "short_final.manifest.json", *,
              mtime: float | None = None) -> Path:
    ws = Path(settings.workspace_dir) / ticker / day
    ws.mkdir(parents=True, exist_ok=True)
    path = ws / name
    path.write_text(json.dumps({"plates_used": ["x/y"], **payload}),
                    encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return ws


class _Word:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word, self.start, self.end = word, start, end


def _words(duration: float, n: int = 120) -> list[_Word]:
    step = duration / n
    return [_Word(f"w{i}", i * step, (i + 1) * step) for i in range(n)]


class _Resolver:
    """Words for every line, and a meme when one is handed in."""

    def __init__(self, meme: Path | None = None) -> None:
        self.meme = meme

    def text_for(self, src: str) -> str | None:
        return "words"

    def image_for(self, src: str):
        return self.meme if src == MEME_SRC else None

    def list_for(self, src: str):
        return None


def _bare(sid: str, **extra) -> dict:
    return {"id": sid, "plate": None, "captions": False,
            "text": [{"src": f"script.{sid}", "size_fh": 0.07}], **extra}


def _fmt(*shots: dict):
    return parse_format({"format": "t", "aspect": "9x16",
                         "frame": {"w": 1080, "h": 1920},
                         "shots": list(shots)})


def _still(tmp_path: Path, size=(800, 800), name="still") -> Path:
    p = tmp_path / f"{name}.png"
    Image.new("RGB", size, (30, 160, 90)).save(p)
    return p


@pytest.fixture(scope="module")
def reg():
    from config import Settings
    from pipeline.plates import load_plates
    return load_plates(Settings(_env_file=None).assets_dir)


# ---------------------------------------------------------------------------
# The picker
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, fmt", [("short_valid", "short"),
                                       ("earnings_valid", "earnings"),
                                       ("macro_valid", "macro")])
def test_each_short_format_finds_a_meme_in_the_owned_library(settings, name,
                                                             fmt):
    script = _script(name, settings)
    choice = choose_for_short(script, settings, fmt=fmt,
                              seed=script.content_sha())

    assert choice, choice.why
    assert choice.key in MemeLibrary(settings).index()
    assert choice.score >= MEME_FLOOR and choice.matched
    # The still is made from the library file, into the cache, as a PNG.
    assert choice.path.exists() and choice.path.suffix == ".png"
    assert Path(settings.cache_dir) in choice.path.parents
    assert (settings.assets_dir / "meme_library" / choice.file).exists()


def test_the_same_script_always_gets_the_same_meme(settings):
    script = _script("macro_valid", settings)
    picks = {choose_for_short(script, settings, fmt="macro",
                              seed=script.content_sha()).key
             for _ in range(3)}
    assert len(picks) == 1


def test_a_tie_is_broken_by_the_seed_and_both_can_win(settings, tmp_path):
    lib = _library(tmp_path, {
        "one": ({"tags": ["beat-sold-off"], "use_when": ""}, (800, 800)),
        "two": ({"tags": ["beat-sold-off"], "use_when": ""}, (800, 800)),
    })
    seen = {choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                             direction="down", seed=f"s{i}",
                             library=lib).key for i in range(24)}
    assert seen == {"one", "two"}
    again = choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                             direction="down", seed="s3", library=lib)
    assert again.key == choose_for_short(
        BEAT_SOLD_OFF, settings, fmt="earnings", direction="down", seed="s3",
        library=lib).key


def test_a_meme_drawn_for_the_situation_beats_one_that_only_fits_it(
        settings, tmp_path):
    lib = _library(tmp_path, {
        "harold": ({"tags": ["hiding-the-pain", "earnings"],
                    "use_when": "smiling through it"}, (800, 800)),
        "new-beat-sold-off": ({"tags": ["beat-sold-off", "earnings"],
                               "use_when": ""}, (800, 1000)),
    })
    choice = choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                              direction="down", library=lib)
    assert choice.key == "new-beat-sold-off"
    assert "beat-sold-off" in choice.matched
    assert "harold" in choice.candidates


def test_nothing_above_the_floor_means_no_meme_and_says_why(settings,
                                                            tmp_path):
    lib = _library(tmp_path, {
        "crypto": ({"tags": ["crypto", "bitcoin"], "use_when": "a coin moons"},
                   (800, 800)),
    })
    choice = choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                              direction="down", library=lib)
    assert not choice and choice.path is None
    assert str(MEME_FLOOR) in choice.why


def test_use_when_counts_but_never_outvotes_a_tag(settings, tmp_path):
    lib = _library(tmp_path, {
        "plain": ({"tags": ["hiding-the-pain"], "use_when": ""}, (800, 800)),
        "worded": ({"tags": ["hiding-the-pain"],
                    "use_when": "an estimate beat that did not matter"},
                   (800, 800)),
        "only-words": ({"tags": ["unrelated"],
                        "use_when": "beat estimate stock fell eight percent "
                                    "matter"},
                       (800, 800)),
    })
    choice = choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                              direction="down", library=lib)
    assert choice.key == "worded"
    # Every word of it shared, capped, and no tag: under the floor alone.
    assert "only-words" not in choice.candidates


def test_a_meme_from_a_recent_video_is_not_told_again(settings, tmp_path):
    lib = _library(tmp_path, {
        "best": ({"tags": ["beat-sold-off", "earnings"], "use_when": ""},
                 (800, 800)),
        "next": ({"tags": ["hiding-the-pain", "earnings"], "use_when": ""},
                 (800, 800)),
    })
    kw = dict(fmt="earnings", direction="down", library=lib)
    assert choose_for_short(BEAT_SOLD_OFF, settings, **kw).key == "best"
    assert choose_for_short(BEAT_SOLD_OFF, settings, avoid={"best"},
                            **kw).key == "next"
    # A RULE, NOT A PREFERENCE: a repeated joke is worse than none.
    none = choose_for_short(BEAT_SOLD_OFF, settings, avoid={"best", "next"},
                            **kw)
    assert not none and "recent" in none.why


@pytest.mark.parametrize("size", [(2400, 800), (600, 1800)])
def test_a_meme_too_wide_or_too_tall_for_a_vertical_frame_is_never_picked(
        settings, tmp_path, size):
    lib = _library(tmp_path, {
        "misshapen": ({"tags": ["beat-sold-off"], "use_when": ""}, size),
    })
    assert not choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                                direction="down", library=lib)


def test_a_meme_marked_for_the_long_only_is_never_picked_for_a_short(
        settings, tmp_path):
    lib = _library(tmp_path, {
        "screenshot": ({"tags": ["beat-sold-off"], "use_when": "",
                        "shorts": False}, (800, 800)),
    })
    assert not choose_for_short(BEAT_SOLD_OFF, settings, fmt="earnings",
                                direction="down", library=lib)


def test_the_whole_page_screenshots_are_kept_to_the_long(settings):
    index = MemeLibrary(settings).index()
    for stem in ("futures-physical-delivery-crude-oil",
                 "futures-physical-delivery-live-cattle"):
        assert index[stem]["shorts"] is False


def test_diluted_eps_on_the_sheet_is_not_dilution():
    row = SimpleNamespace(label="Diluted EPS", values=["1.00", "1.40"])
    shares = SimpleNamespace(label="Shares outstanding (m)",
                             values=["100", "104"])
    reading = memes.read_script(
        SimpleNamespace(verdict="Diluted EPS rose.", numbers=[row, shares]))
    assert "dilution" not in {s.tag for s in reading.situations}
    grew = SimpleNamespace(label="Shares outstanding (m)",
                           values=["100", "125"])
    reading = memes.read_script(SimpleNamespace(numbers=[grew]))
    assert "dilution" in {s.tag for s in reading.situations}


def test_a_short_never_reaches_past_the_library(settings, monkeypatch,
                                               tmp_path):
    def refuse(*_a, **_k):
        raise AssertionError("a short asked for a meme beyond the library")

    monkeypatch.setattr(memes, "animated_providers", refuse)
    monkeypatch.setattr(memes.MemeManager, "resolve", refuse)
    monkeypatch.setattr(memes.MemeManager, "__init__", refuse)
    empty = _library(tmp_path, {})
    choice = choose_for_short(_script("short_valid", settings), settings,
                              library=empty)
    # No filler card either: an empty library is no meme, not a grey box.
    assert not choice and choice.path is None
    assert choose_for_short(_script("short_valid", settings), settings)


# ---------------------------------------------------------------------------
# What recent videos showed
# ---------------------------------------------------------------------------

def test_recent_memes_reads_both_lanes_and_skips_this_workspace(settings):
    mine = _manifest(settings, "AAA", "2026-09-01",
                     {"meme": {"key": "shown-in-this-video"}})
    _manifest(settings, "BBB", "2026-09-02", {"meme": {"key": "short-one"}})
    _manifest(settings, "CCC", "2026-09-03", {"segments": [
        {"kind": "meme",
         "attribution": memes.LIBRARY_ATTRIBUTION.format(stem="long-one")},
        {"kind": "meme", "attribution": "giphy"}]}, name="manifest.json")
    _manifest(settings, "DDD", "2026-09-04", {"meme": {"key": None}})

    got = recent_memes(settings, exclude=mine)
    assert got == {"short-one", "long-one"}


def test_a_filings_manifest_is_not_a_video(settings):
    ws = Path(settings.workspace_dir) / "EEE" / "2026-09-05"
    ws.mkdir(parents=True)
    (ws / "filings_manifest.json").write_text(
        json.dumps({"meme": {"key": "not-a-render"}}), encoding="utf-8")
    assert recent_memes(settings) == set()


def test_the_window_counts_videos_not_passes(settings):
    _manifest(settings, "OLD", "2026-09-01", {"meme": {"key": "old"}},
              mtime=1_000)
    _manifest(settings, "MID", "2026-09-02", {"meme": {"key": "mid-proof"}},
              name="short_proof.manifest.json", mtime=2_000)
    _manifest(settings, "MID", "2026-09-02", {"meme": {"key": "mid"}},
              mtime=2_100)
    _manifest(settings, "NEW", "2026-09-03", {"meme": {"key": "new"}},
              mtime=3_000)
    assert recent_memes(settings, window=2) == {"new", "mid", "mid-proof"}


def test_the_long_credits_a_library_meme_in_a_form_the_rotation_reads(settings):
    stem = sorted(MemeLibrary(settings).index())[0]
    asset = memes.MemeManager(settings, providers=[]).resolve(stem)
    assert asset.source == "library"
    assert memes_in_manifest({"segments": [
        {"kind": "meme", "attribution": asset.attribution}]}) == {stem}


# ---------------------------------------------------------------------------
# The template grammar
# ---------------------------------------------------------------------------

def test_a_meme_place_is_read_in_either_spelling():
    fmt = _fmt(_bare("a", meme={"at": "start", "notes": "why here"}),
               _bare("b"))
    assert fmt.shot("a").meme.at == "start"
    assert fmt.shot("b").meme is None
    assert _fmt(_bare("a", meme="end")).shot("a").meme.at == "end"


@pytest.mark.parametrize("meme, says", [
    ({"at": "end", "hold_s": 2}, "unknown key"),
    ({"at": "middle"}, "must be one of"),
    ({}, "must be one of"),
    (3, "is not"),
])
def test_a_malformed_meme_place_is_refused(meme, says):
    with pytest.raises(TemplateError, match=says):
        _fmt(_bare("a", meme=meme))


def test_a_format_has_one_meme_place_at_most():
    with pytest.raises(TemplateError, match="one place for a meme"):
        _fmt(_bare("a", meme="end"), _bare("b", meme="start"))


def test_a_repeat_cannot_carry_the_meme_place():
    with pytest.raises(TemplateError, match="repeat"):
        _fmt({"id": "a", "plate": None, "meme": "end",
              "repeat": {"src": "script.consequences", "arrange": "sequence"},
              "text": [{"src": "script.a", "size_fh": 0.07}],
              "captions": False})


@pytest.mark.parametrize("name, shot", [("short", "payoff"),
                                        ("earnings", "so-what"),
                                        ("macro", "so-what")])
def test_each_short_format_places_its_meme_at_the_end_of_the_verdict(name,
                                                                     shot):
    fmt = load_format(name)
    places = [sh for sh in fmt.shots if sh.meme]
    assert [sh.id for sh in places] == [shot]
    assert places[0].meme.at == "end"
    # The verdict is the shot the mix treats as the payoff, so the guard
    # that keeps the meme off the drop is the mix's own.
    assert shot in PAYOFF_SHOTS


def test_a_template_with_no_meme_place_still_loads():
    raw = json.loads(Path("templates/shots/macro.json").read_text(encoding="utf-8"))
    for shot in raw["shots"]:
        shot.pop("meme", None)
    assert not any(sh.meme for sh in parse_format(raw).shots)


# ---------------------------------------------------------------------------
# The compositor
# ---------------------------------------------------------------------------

def _build(fmt, reg, meme: Path | None, duration: float = 12.0, *,
           avoid=(), words=None):
    spans = resolve_spans(fmt, words or _words(duration), duration, {})
    return spans, build_layers(fmt, spans, _Resolver(meme), reg,
                               aspect="9x16", seed="t", avoid=avoid)


def test_the_meme_overlays_the_end_of_its_shot_and_moves_no_other(reg,
                                                                 tmp_path):
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"), _bare("close"))
    spans, with_meme = _build(fmt, reg, _still(tmp_path))
    _, without = _build(fmt, reg, None)

    meme = placed_meme(with_meme)
    span = next(sp for sp in spans if sp.shot.id == "payoff")
    assert meme is not None and meme.shot_id == "payoff"
    assert meme.t_end == pytest.approx(span.end)
    hold = meme.t_end - meme.t_start
    assert MEME_HOLD_S[0] - 1e-6 <= hold <= MEME_HOLD_S[1] + 1e-6
    assert hold <= (span.end - span.start) * MEME_SHARE + 1e-6

    # OVERLAID, NOT INSERTED: the same spans, and every layer that is not the
    # meme's exactly as it was.
    assert [(s.shot.id, s.start, s.end) for s in with_meme.spans] == \
           [(s.shot.id, s.start, s.end) for s in without.spans]
    rest = [(l.name, l.t_start, l.t_end) for l in with_meme.layers
            if l.slot != MEME_SRC]
    assert rest == [(l.name, l.t_start, l.t_end) for l in without.layers]


def test_the_meme_sits_whole_inside_a_frames_plate(reg, tmp_path):
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    for size in ((1200, 900), (800, 1000), (1600, 820)):
        _, result = _build(fmt, reg, _still(tmp_path, size, f"m{size[0]}"))
        meme = placed_meme(result)
        frame = next(l for l in result.layers
                     if l.kind == "plate" and l.slot == MEME_SRC)
        assert frame.entry_key.startswith("frames/media-frame-")
        assert (frame.t_start, frame.t_end) == (meme.t_start, meme.t_end)
        assert frame.z < meme.z
        # Inside the frame's window, and the meme's own shape: fitted, not
        # cropped.
        plate = reg.get(frame.entry_key)
        ax, ay, aw, ah = _slot_in_frame(plate, "media",
                                        (frame.x, frame.y, frame.w, frame.h))
        assert ax <= meme.x and meme.x + meme.w <= ax + aw
        assert ay <= meme.y and meme.y + meme.h <= ay + ah
        assert meme.w / meme.h == pytest.approx(size[0] / size[1], rel=0.01)
        assert frame.entry_key in result.plates_used


def test_the_meme_is_drawn_over_everything_in_its_shot(reg, tmp_path):
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    _, result = _build(fmt, reg, _still(tmp_path))
    frame_z = min(l.z for l in result.layers if l.slot == MEME_SRC)
    others = [l.z for l in result.for_shot("payoff") if l.slot != MEME_SRC]
    assert frame_z > max(others)


def test_the_payoff_drop_and_the_number_land_before_any_meme(reg, tmp_path):
    still = _still(tmp_path)
    # At the end of the shot BEFORE the payoff is inside the drop.
    fmt = _fmt(_bare("a"), _bare("b", meme="end"), _bare("payoff"))
    _, result = _build(fmt, reg, still, duration=15.0)
    assert placed_meme(result) is None
    assert any(s.startswith("b.meme <- no room") for s in result.skipped)
    # At the START of the payoff is on the hit.
    fmt = _fmt(_bare("a"), _bare("payoff", meme="start"))
    _, result = _build(fmt, reg, still, duration=15.0)
    assert placed_meme(result) is None
    # At the end of it, the drop, the hit and the first read are all clear.
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    spans, result = _build(fmt, reg, still, duration=15.0)
    meme = placed_meme(result)
    payoff = next(sp for sp in spans if sp.shot.id == "payoff")
    for a, b in payoff_guards(spans):
        assert meme.t_start >= b or meme.t_end <= a
    assert meme.t_start >= payoff.start + DROP_S


def test_a_meme_holds_the_end_it_was_placed_at_for_a_third_at_most():
    fmt = _fmt(_bare("payoff", meme="end"))
    spans = resolve_spans(fmt, _words(4.0), 4.0, {})
    start, end = meme_window(spans[0], spans)
    assert end == pytest.approx(spans[0].end)
    assert end - start == pytest.approx(4.0 * MEME_SHARE)
    # Its own payoff guard is behind it: the drop, the hit, the first read.
    assert start >= max(b for _a, b in payoff_guards(spans))
    short = resolve_spans(fmt, _words(2.7), 2.7, {})
    assert meme_window(short[0], short) is None


def test_a_span_too_short_to_hold_a_meme_gets_none(reg, tmp_path):
    fmt = _fmt(_bare("a"), _bare("b", meme="end"), _bare("c"), _bare("d"))
    _, result = _build(fmt, reg, _still(tmp_path), duration=9.0)
    assert placed_meme(result) is None
    assert [s for s in result.skipped if ".meme <- no room" in s]


def test_no_meme_from_the_library_draws_nothing(reg):
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    _, result = _build(fmt, reg, None)
    assert not [l for l in result.layers if l.slot == MEME_SRC]
    assert "payoff.meme <- nothing in the library fits" in result.skipped


def test_a_meme_over_the_host_is_a_cutaway_not_a_sticker(reg, tmp_path):
    fmt = _fmt(_bare("a"),
               {"id": "turn", "plate": "room/talk", "meme": "start",
                "host": {"pose": "host/close-up", "slot": "host-anchor"}})
    _, result = _build(fmt, reg, _still(tmp_path))
    assert placed_meme(result) is not None
    assert result.of_kind("host")
    assert check_invariants(fmt, result, host_shots=["turn"]) == []


def test_the_frame_rotates_off_what_recent_videos_used(reg):
    keys = [f"{t}-9x16" for t in MEDIA_TREATMENTS]
    for fresh in keys:
        avoid = set(keys) - {fresh}
        assert _meme_frame(reg, "9x16", seed="x", avoid=avoid).base_key == fresh
    # A preference: with every treatment recent, one is still drawn.
    assert _meme_frame(reg, "9x16", seed="x", avoid=set(keys)) is not None


def test_the_frame_fills_the_frame_it_is_drawn_in(reg, tmp_path):
    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    _, result = _build(fmt, reg, _still(tmp_path))
    frame = next(l for l in result.layers
                 if l.kind == "plate" and l.slot == MEME_SRC)
    plate = reg.get(frame.entry_key)
    assert (frame.w, frame.h) == _fit(plate, result.frame)


# ---------------------------------------------------------------------------
# The renderer's half: the resolver asks, the manifest records
# ---------------------------------------------------------------------------

def test_the_resolver_answers_the_meme_place_from_the_library(settings,
                                                             workspace):
    from pipeline.render_short import ShortResolver

    script = _script("macro_valid", settings)
    first = ShortResolver(script=script, workdir=workspace / "render_short",
                          settings=settings, format_name="macro")
    path = first.image_for(MEME_SRC)
    assert path is not None and path == first.meme_choice.path
    picked = first.meme_choice.key

    # Its own workspace's manifest does not count against it ...
    (workspace / "short_proof.manifest.json").write_text(json.dumps(
        {"plates_used": ["x/y"], "meme": {"key": picked}}), encoding="utf-8")
    again = ShortResolver(script=script, workdir=workspace / "render_short",
                          settings=settings, format_name="macro")
    assert again.meme().key == picked
    # ... another video's does.
    _manifest(settings, "OTHER", "2026-06-30", {"meme": {"key": picked}})
    other = ShortResolver(script=script, workdir=workspace / "render_short",
                          settings=settings, format_name="macro")
    assert other.meme().key != picked


def test_the_manifest_line_names_the_meme_or_says_why_not(reg, tmp_path):
    from pipeline.render_short import _meme_record

    fmt = _fmt(_bare("a"), _bare("payoff", meme="end"))
    still = _still(tmp_path, name="the-joke")
    _, result = _build(fmt, reg, still)
    line = _meme_record(_Resolver(still), result)
    assert line["key"] == "the-joke" and line["source"] == "library"
    assert line["shot"] == "payoff"
    assert line["frame"].startswith("frames/media-frame-")
    assert line["end_s"] > line["start_s"]
    assert memes_in_manifest({"meme": line}) == {"the-joke"}

    _, none = _build(fmt, reg, None)
    line = _meme_record(_Resolver(None), none)
    assert line["key"] is None and "nothing in the library fits" in line["why"]
    assert memes_in_manifest({"meme": line}) == set()


def test_a_rendered_short_records_its_meme_and_counts_it_as_owned(
        settings, tmp_path, short_valid_json):
    from pipeline.parser_short import parse_short_script
    from pipeline.provenance import Provenance
    from pipeline.render_short import render_short
    from pipeline.tts import TTSEngine

    small = settings.model_copy(update={"short_width": 270,
                                        "short_height": 480})
    script, _ = parse_short_script(short_valid_json, settings=small)
    tts = TTSEngine(small).synthesize(script.audio_script, fmt="short",
                                      free_only=True)
    _out, manifest_path = render_short(script, tts, tmp_path, small,
                                       proof=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    meme = manifest["meme"]
    assert meme["key"] and meme["shot"] == "payoff"
    assert meme["key"] in MemeLibrary(small).index()
    assert any(meme["frame"] == k for k in manifest["plates_used"])
    payoff = next(s for s in manifest["shots"] if s["id"] == "payoff")
    assert payoff["start_s"] < meme["start_s"] < meme["end_s"] <= payoff["end_s"]
    assert manifest["provenance"]["visuals"] == {"library": 1}
    visuals = next(ln for ln in Provenance.from_json(manifest["provenance"])
                   .render_text().splitlines() if ln.startswith("visuals"))
    assert "1 owned" in visuals
