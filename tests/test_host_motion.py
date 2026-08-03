"""The face moves when nobody is speaking.

`build_host_clip` composed exactly two states — mouth-open and mouth-closed —
plus a boil on held frames. Over a forty-minute cut that is a face that only
ever talks, and it is the most-viewed element in the channel.

`-blink` and `-idle` strips arrive by naming convention through the registry,
the same way `-talk` does. The artwork has not shipped yet, so the bar these
hold is twofold: the scheduling is right for when it does, and a kit without
the strips renders exactly as it did before — silently, never raising.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from pipeline.host import (
    BLINK_EVERY_S,
    FLAP_HZ,
    IDLE_MIN_SPAN_S,
    blink_intervals,
    blink_schedule,
    build_host_clip,
    mouth_schedule,
    quiet_spans,
    shots,
)
from pipeline.kit import Kit
from pipeline.models import WordTimestamp

ROOT = Path(__file__).resolve().parents[1]


def words(*spans: tuple[float, float]) -> list[WordTimestamp]:
    return [WordTimestamp(word="w", start=a, end=b,
                          char_start=i * 2, char_end=i * 2 + 1)
            for i, (a, b) in enumerate(spans)]


# --------------------------------------------------------------------------
# Where the quiet is.
# --------------------------------------------------------------------------

def test_quiet_is_the_complement_of_speech():
    q = quiet_spans(words((1.0, 2.0), (3.0, 4.0)), 0.0, 5.0)
    assert q == [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]


def test_a_segment_with_no_words_is_all_quiet():
    assert quiet_spans([], 2.0, 9.0) == [(2.0, 9.0)]


def test_speech_running_past_the_segment_is_clipped():
    q = quiet_spans(words((0.0, 10.0)), 2.0, 5.0)
    assert q == []


# --------------------------------------------------------------------------
# When he blinks.
# --------------------------------------------------------------------------

def test_the_interval_is_in_the_resting_band():
    times = blink_intervals(0.0, 60.0, seed="shot-a")
    assert len(times) >= 8, f"only {len(times)} blinks in a silent minute"
    gaps = [b - a for a, b in zip(times, times[1:])]
    lo, hi = BLINK_EVERY_S
    assert lo <= min(gaps) and max(gaps) <= hi


def test_two_shots_do_not_blink_in_lockstep():
    """Seeded per shot. Shared timing is the specific thing that reads as a
    puppet — two faces in one cut closing their eyes together."""
    assert (blink_intervals(0.0, 60.0, seed="shot-a")
            != blink_intervals(0.0, 60.0, seed="shot-b"))


def test_the_same_shot_blinks_the_same_way_twice():
    """Deterministic, or a re-render is a different video."""
    assert (blink_intervals(0.0, 30.0, seed="s")
            == blink_intervals(0.0, 30.0, seed="s"))


def test_a_blink_never_lands_mid_flap():
    """The whole strip plays over CLOSED-mouth frames, or it is not scheduled.

    This is the checkable form of "a blink belongs in a gap". The looser
    form — "where nobody is speaking" — is not usable: word timings arrive
    wall to wall, so a talking shot has no acoustic silence in it at all.
    """
    fps = 30
    plan = mouth_schedule(words((0.0, 30.0)), 0.0, 30.0, fps)
    assert any(plan), "the fixture must actually flap"
    starts = blink_schedule(plan, fps, seed="s", length=3)
    assert starts, "wall-to-wall speech still has closed-mouth runs to blink in"
    for j in starts:
        assert not any(plan[j:j + 3]), f"blink at frame {j} runs over an open mouth"


def test_wall_to_wall_speech_still_blinks():
    """The regression this replaced: zero blinks across a whole video.

    Measured on the fixture short, EVERY gap between consecutive words is
    0.000s. Under a silence-only rule the face blinked exactly zero times in
    a fifty-second cut, which is the static face the feature exists to fix.
    """
    fps = 30
    plan = mouth_schedule(words((0.0, 14.0)), 0.0, 14.0, fps)
    starts = blink_schedule(plan, fps, seed="s", length=3)
    assert len(starts) >= 2, f"14s of continuous speech gave {len(starts)} blinks"


def test_a_mouth_that_never_closes_gets_no_blink():
    """Forcing one onto an open mouth is worse than skipping it."""
    assert blink_schedule([True] * 300, 30, seed="s", length=3) == []


def test_blinks_do_not_flutter():
    plan = [False] * 900
    starts = blink_schedule(plan, 30, seed="s", length=3)
    assert all(b - a >= 6 for a, b in zip(starts, starts[1:]))


def test_a_segment_shorter_than_the_first_interval_may_have_none():
    assert blink_schedule([False] * 15, 30, seed="s", length=3) == []


# --------------------------------------------------------------------------
# A kit that ships the strips, built here because the artwork has not landed.
# --------------------------------------------------------------------------

def _png(path: Path, size, fill) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, fill).save(path)


@pytest.fixture
def kit_with_strips(tmp_path) -> Kit:
    """A minimal kit whose one shot ships `-talk`, `-blink` and `-idle`.

    Built rather than mocked: the point of the naming convention is that
    ingest drops a strip beside its base and the renderer finds it with no
    code change, and only a real registry read proves that.
    """
    root = tmp_path / "kit"
    entries: dict[str, dict] = {}
    # (frame count, red channel). The red channel is the strip's identity, so
    # a frame test can name which strip it is looking at — deriving it from
    # the suffix length collided `-talk` with `-idle`.
    STRIPS = {"": (1, 10), "-talk": (1, 60), "-blink": (3, 110), "-idle": (4, 160)}
    for suffix, (n, red) in STRIPS.items():
        name = f"at-desk-open{suffix}"
        frames = []
        for i in range(n):
            rel = f"chapters/cold-open/{name}-{i}.png"
            _png(root / rel, (40, 40), (red, 20 * (i + 1), 30, 255))
            frames.append(rel)
        entries[f"chapters/cold-open/{name}"] = {
            "family": "chapters/cold-open", "name": name, "frames": frames,
            "frameCount": n, "playback": "static" if n == 1 else "loop",
            "fps": 12, "canvas": {"w": 40, "h": 40}, "aspect": "1:1",
            "alpha": True, "slots": [], "source": "test",
        }
    (root / "kit-registry.json").write_text(json.dumps({
        "kit": "test", "version": 2, "roots": {"test": ""}, "assets": entries,
    }), encoding="utf-8")
    return Kit(root)


def test_the_registry_hands_over_the_strips_with_no_code_change(kit_with_strips):
    bank = shots(kit_with_strips, "open")
    assert len(bank) == 1
    shot = bank[0]
    assert shot.blink is not None and shot.blink.frame_count == 3
    assert shot.idle is not None and shot.idle.frame_count == 4


def test_a_single_frame_strip_is_not_micro_motion(tmp_path):
    """One frame cannot animate. Saying so means the shot boils instead of
    swapping to an identical drawing eight times a minute."""
    root = tmp_path / "kit"
    _png(root / "a/base-0.png", (8, 8), (0, 0, 0, 255))
    _png(root / "a/base-blink-0.png", (8, 8), (0, 0, 0, 255))
    entry = lambda name, n: {  # noqa: E731
        "family": "a", "name": name,
        "frames": [f"a/{name}-{i}.png" for i in range(n)], "frameCount": n,
        "playback": "static", "fps": 0, "canvas": {"w": 8, "h": 8},
        "aspect": "1:1", "alpha": True, "slots": [], "source": "t"}
    (root / "kit-registry.json").write_text(json.dumps({
        "kit": "t", "version": 2, "roots": {"t": ""},
        "assets": {"a/base": entry("base", 1), "a/base-blink": entry("base-blink", 1)},
    }), encoding="utf-8")
    assert Kit(root).micro_motion("a/base", "-blink") is None


def test_a_shot_with_no_strips_resolves_to_none():
    """The real kit today. Every shot must still build."""
    from config import Settings
    from pipeline.kit import load_kit

    kit = load_kit(Settings().assets_dir)
    bank = shots(kit, "open")
    assert bank, "the real kit must still supply cold-open shots"
    # Whatever the artwork state is, resolution must not raise.
    for shot in bank:
        assert shot.blink is None or shot.blink.frame_count >= 2
        assert shot.idle is None or shot.idle.frame_count >= 2


# --------------------------------------------------------------------------
# What reaches the clip.
# --------------------------------------------------------------------------

def _frame_colours(clip: Path, tmp: Path) -> list[tuple]:
    import subprocess

    out = tmp / "f"
    out.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip),
                    str(out / "%03d.png")], check=True, capture_output=True)
    return [Image.open(p).convert("RGB").getpixel((1, 1))
            for p in sorted(out.glob("*.png"))]


def test_the_blink_strip_reaches_the_clip(kit_with_strips, tmp_path, settings):
    """Pixel evidence. A blink scheduled in a dict is not a blink on screen."""
    clip = tmp_path / "host.mov"
    report: dict = {}
    built = build_host_clip(
        [], 0.0, 12.0, clip, kit=kit_with_strips, settings=settings,
        fps=12, role="open", report=report)
    assert built is not None
    assert report["has_blink"] and report["has_idle"]
    assert report["blinks"] >= 1, report
    colours = set(_frame_colours(clip, tmp_path))
    assert any(abs(c[0] - 110) <= 2 for c in colours), \
        f"no blink frame in the clip; saw {sorted(colours)}"


def test_the_idle_strip_carries_a_long_silence(kit_with_strips, tmp_path, settings):
    report: dict = {}
    build_host_clip([], 0.0, 12.0, tmp_path / "h.mov", kit=kit_with_strips,
                    settings=settings, fps=12, role="open", report=report)
    assert report["idle_frames"] > 0, \
        "twelve seconds of silence and the idle strip never played"


def test_a_short_gap_is_not_long_enough_to_idle(kit_with_strips, tmp_path, settings):
    """The idle is a shift of weight, not a fidget between words."""
    gap = IDLE_MIN_SPAN_S * 0.4
    w = words((0.0, 3.0), (3.0 + gap, 6.0))
    report: dict = {}
    build_host_clip(w, 0.0, 6.0, tmp_path / "h.mov", kit=kit_with_strips,
                    settings=settings, fps=12, role="open", report=report)
    assert report["idle_frames"] == 0, report


def test_the_real_kit_still_builds_a_host(tmp_path, settings):
    """The state the artwork is actually in. Silent degrade, never a raise."""
    from config import Settings
    from pipeline.kit import load_kit

    kit = load_kit(Settings().assets_dir)
    report: dict = {}
    built = build_host_clip(
        words((0.0, 2.0)), 0.0, 3.0, tmp_path / "h.mov", kit=kit,
        settings=settings, fps=12, role="open", display_w=120, report=report)
    assert built is not None, "the host must build with no micro-motion artwork"
    clip, _ = built
    assert len(_frame_colours(clip, tmp_path)) == 36, "3s at 12fps"
    # Whatever ships, the two must agree: blinks only ever come from a strip.
    assert report["has_blink"] or report["blinks"] == 0


def test_a_strip_that_fails_to_load_is_not_fatal(kit_with_strips, tmp_path,
                                                 settings, monkeypatch):
    """A face is never worth a failed render."""
    shot = shots(kit_with_strips, "open")[0]
    # Truncate the blink artwork after the kit has indexed it.
    for frame in shot.blink.frames:
        Path(frame).write_bytes(b"not a png")
    report: dict = {}
    built = build_host_clip(
        [], 0.0, 6.0, tmp_path / "h.mov", kit=kit_with_strips,
        settings=settings, fps=12, role="open", report=report)
    assert built is not None
    assert report["blinks"] == 0


# --------------------------------------------------------------------------
# The gap is a line item, not a silence.
# --------------------------------------------------------------------------

def test_the_doctor_names_the_shots_that_cannot_blink():
    """Silent degrade is the right failure mode and an invisible one.

    A face that never blinks looks like a rendering choice rather than like
    missing artwork, so the gap list an operator actually reads has to carry
    it — that list is the input to the next batch of art.
    """
    from config import Settings
    from pipeline.gates import kit_doctor, kit_doctor_text

    settings = Settings()
    _, stats = kit_doctor(_EmptyScript(), settings)
    missing = stats["missing_micro_motion"]
    assert set(missing) == {"-blink", "-idle"}
    text = kit_doctor_text(settings)
    if any(missing.values()):
        assert "cannot blink or settle" in text
        assert "no code change is needed" in text


class _EmptyScript:
    ticker = "EXMPL"
    inline_events: list = []

    def evidence_events(self):
        return []
