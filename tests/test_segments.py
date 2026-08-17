"""Per-segment encoding: cache, parallelism, resumability, equivalence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from config import Settings
from pipeline.parser_long import parse_long_script
from pipeline.render_common import (
    RenderError,
    encode_profile,
    ffprobe_duration,
    set_render_politeness,
)
from pipeline.render_long import render_long
from pipeline.segments import (
    SegmentSpec,
    cache_size_mb,
    concat_clips,
    encode_segments,
    plan_workers,
    prune_cache,
)
from pipeline.tts import TTSEngine


# ------------------------------------------------------------ politeness


def test_workers_times_threads_never_exceeds_the_budget():
    """The cap is an aggregate. Eight ffmpeg processes each taking half the
    machine is not politeness."""
    for budget in range(1, 33):
        workers, per = plan_workers(budget, n_segments=64)
        assert workers >= 1 and per >= 1
        assert workers * per <= budget, f"budget {budget} oversubscribed"


def test_workers_never_exceed_the_work():
    workers, _ = plan_workers(16, n_segments=2)
    assert workers <= 2


def test_render_thread_fraction_reaches_the_parallel_encoder_in_aggregate():
    """RENDER_THREAD_FRACTION is a promise about the whole render, not about
    one ffmpeg. The segment encoder runs several at once, so the fraction has
    to survive the whole chain: setting -> resolved_render_threads ->
    render_thread_budget -> plan_workers -> per-worker `-threads`.

    Checked end to end rather than at `plan_workers` alone, because every
    earlier link is somewhere the cap could quietly stop applying.
    """
    import os

    from pipeline.render_common import render_thread_budget

    cores = os.cpu_count() or 4
    for fraction in (0.25, 0.5, 1.0):
        s = Settings(render_thread_fraction=fraction, _env_file=None)
        set_render_politeness(s)

        expected = max(1, min(cores, round(cores * fraction)))
        assert s.resolved_render_threads() == expected
        assert render_thread_budget() == expected

        workers, per = plan_workers(render_thread_budget(), n_segments=64)
        assert workers * per <= expected, (
            f"fraction {fraction}: {workers}x{per} threads exceeds the "
            f"{expected}-thread budget")


def test_an_explicit_thread_pin_also_reaches_the_parallel_encoder():
    s = Settings(render_threads=4, _env_file=None)
    set_render_politeness(s)
    from pipeline.render_common import render_thread_budget

    assert render_thread_budget() == 4
    workers, per = plan_workers(render_thread_budget(), n_segments=64)
    assert workers * per <= 4


# ------------------------------------------------------- spec + hashing


def _spec(tmp_path: Path, index: int = 0, duration: float = 0.5,
          colour: str = "red") -> SegmentSpec:
    return SegmentSpec(
        index=index, kind="test", duration=duration,
        width=64, height=64, fps=15,
        inputs=(("-f", "lavfi", "-t", f"{duration}",
                 "-i", f"color=c={colour}:s=64x64:r=15"),),
        filter_chain="[0:v]scale=64:64,setsar=1,format=yuv420p[out]",
    )


def test_the_hash_changes_with_anything_that_changes_the_pixels(tmp_path, settings):
    profile = encode_profile(settings, "long", draft=True)
    base = _spec(tmp_path)
    assert base.content_hash(profile) == _spec(tmp_path).content_hash(profile)

    assert _spec(tmp_path, duration=0.9).content_hash(profile) != \
        base.content_hash(profile)
    assert _spec(tmp_path, colour="blue").content_hash(profile) != \
        base.content_hash(profile)

    from dataclasses import replace
    assert replace(base, width=128).content_hash(profile) != base.content_hash(profile)
    assert replace(base, fps=30).content_hash(profile) != base.content_hash(profile)
    assert replace(base, layout="two-shot").content_hash(profile) != \
        base.content_hash(profile)


def test_the_hash_ignores_position_in_the_timeline(tmp_path, settings):
    """Removing Ken Burns is what bought this: a still no longer depends on
    where it sits, so the same asset at the same size is the same clip."""
    from dataclasses import replace

    profile = encode_profile(settings, "long", draft=True)
    a = _spec(tmp_path, index=0)
    b = replace(a, index=17)
    assert a.content_hash(profile) == b.content_hash(profile)


def test_a_changed_input_file_busts_the_hash(tmp_path, settings):
    profile = encode_profile(settings, "long", draft=True)
    asset = tmp_path / "a.png"
    from PIL import Image
    Image.new("RGB", (32, 32), (1, 2, 3)).save(asset)
    spec = SegmentSpec(
        index=0, kind="img", duration=0.4, width=32, height=32, fps=15,
        inputs=(("-loop", "1", "-t", "0.4", "-i", str(asset)),),
        filter_chain="[0:v]scale=32:32,setsar=1,format=yuv420p[out]",
    )
    before = spec.content_hash(profile)
    Image.new("RGB", (32, 32), (9, 9, 9)).save(asset)   # same name, new bytes
    assert spec.content_hash(profile) != before


# ------------------------------------------------------ encode + cache


def test_segments_encode_then_come_back_from_cache(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    specs = [_spec(tmp_path, index=i, colour=c)
             for i, c in enumerate(("red", "green", "blue"))]
    cache = tmp_path / "cache"

    first = encode_segments(specs, cache, profile, total_threads=4)
    assert len(first.results) == 3
    assert first.cached == 0
    assert all(p.exists() for p in first.clips())

    second = encode_segments(specs, cache, profile, total_threads=4)
    assert second.cached == 3, "an unchanged segment is never re-encoded"
    assert second.clips() == first.clips()


def test_changing_one_segment_re_encodes_only_that_one(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    cache = tmp_path / "cache"
    specs = [_spec(tmp_path, index=i, colour=c)
             for i, c in enumerate(("red", "green", "blue"))]
    encode_segments(specs, cache, profile, total_threads=4)

    specs[1] = _spec(tmp_path, index=1, colour="yellow")
    again = encode_segments(specs, cache, profile, total_threads=4)
    assert again.cached == 2, "only the edited beat is re-encoded"


def test_clips_are_ordered_by_index_not_completion(tmp_path, settings):
    """Workers finish out of order; the concat must not."""
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    specs = [_spec(tmp_path, index=i, duration=0.3 + 0.1 * ((5 - i) % 3),
                   colour=c) for i, c in
             enumerate(("red", "green", "blue", "white", "black", "gray"))]
    run = encode_segments(specs, tmp_path / "c", profile, total_threads=8)
    assert [r.index for r in sorted(run.results, key=lambda r: r.index)] == \
        list(range(6))


def test_a_truncated_cached_clip_is_not_trusted(tmp_path, settings):
    """A reboot mid-encode must not leave a half clip that looks like a hit."""
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    cache = tmp_path / "cache"
    specs = [_spec(tmp_path)]
    run = encode_segments(specs, cache, profile, total_threads=2)
    run.clips()[0].write_bytes(b"not a video")

    again = encode_segments(specs, cache, profile, total_threads=2)
    assert again.cached == 0, "an unreadable clip is re-encoded"
    assert ffprobe_duration(again.clips()[0]) > 0


def test_progress_is_reported_per_segment(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    seen: list[tuple[int, int]] = []
    specs = [_spec(tmp_path, index=i, colour=c)
             for i, c in enumerate(("red", "green", "blue"))]
    encode_segments(specs, tmp_path / "c", profile, total_threads=4,
                    on_progress=lambda d, t: seen.append((d, t)))
    assert [d for d, _ in seen] == [1, 2, 3]
    assert all(t == 3 for _, t in seen)


# --------------------------------------------------------- granular failure


def test_one_bad_segment_does_not_fail_the_render(tmp_path, settings):
    """One unresolvable asset costs one beat, not forty minutes."""
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    bad = SegmentSpec(
        index=1, kind="img", duration=0.4, width=64, height=64, fps=15,
        inputs=(("-i", str(tmp_path / "does-not-exist.png")),),
        filter_chain="[0:v]scale=64:64,setsar=1,format=yuv420p[out]",
    )
    specs = [_spec(tmp_path, index=0), bad, _spec(tmp_path, index=2, colour="blue")]

    def fallback(spec: SegmentSpec) -> SegmentSpec:
        return SegmentSpec(
            index=spec.index, kind="host", duration=spec.duration,
            width=64, height=64, fps=15,
            inputs=(("-f", "lavfi", "-t", f"{spec.duration}",
                     "-i", "color=c=gray:s=64x64:r=15"),),
            filter_chain="[0:v]scale=64:64,setsar=1,format=yuv420p[out]",
            extra_identity=("fallback",),
        )

    run = encode_segments(specs, tmp_path / "c", profile, total_threads=4,
                          fallback=fallback)
    assert len(run.results) == 3
    assert len(run.failures) == 1 and run.failures[0].index == 1
    assert all(p.exists() for p in run.clips())


def test_without_a_fallback_a_bad_segment_raises(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    bad = SegmentSpec(
        index=0, kind="img", duration=0.4, width=64, height=64, fps=15,
        inputs=(("-i", str(tmp_path / "nope.png")),),
        filter_chain="[0:v]scale=64:64,setsar=1,format=yuv420p[out]",
    )
    with pytest.raises(RenderError):
        encode_segments([bad], tmp_path / "c", profile, total_threads=2)


# ------------------------------------------- hardware encoder, mid-run
# Detection proves the GPU can open ONE encode session. It cannot prove it can
# open `workers` of them at once, and consumer cards cap concurrent NVENC
# sessions — so the realistic failure is some arbitrary segment, minutes into a
# forty-minute render. That has to cost a slower clip, not the job.
#
# These used to build EncodeProfile(vcodec="h264_nvenc") and depend on the
# encode FAILING, which is an assertion about the HOST rather than the code: on
# WSL2 with the GPU passed through — the documented target — NVENC succeeds and
# the fallback under test never runs. Two of them then failed the suite, and
# bootstrap.sh refuses to finish on a red suite, so a working GPU became a
# failed install. The third passed on both kinds of machine for different
# reasons and therefore asserted nothing about the degrade on a GPU box.
#
# EncodeProfile.is_hardware is `vcodec != "libx264"`, so a codec name ffmpeg
# does not have is a hardware profile that fails on EVERY machine — including
# the ones that have NVENC, which is exactly where the fallback matters most.
# Skipping when NVENC is present would leave it untested there.
ABSENT_ENCODER = "h264_no_such_encoder"


def _doomed_profile():
    """A hardware profile whose encode cannot succeed anywhere."""
    from pipeline.render_common import EncodeProfile

    p = EncodeProfile(vcodec=ABSENT_ENCODER, preset="p4", crf=32)
    assert p.is_hardware, "the fallback is only tried for hardware profiles"
    return p


def test_a_gpu_that_dies_mid_run_finishes_on_the_cpu(tmp_path, settings):
    """The hardware encode cannot succeed, on any machine: the render still
    completes, on libx264, without raising."""
    set_render_politeness(settings)

    gpu = _doomed_profile()
    cpu = gpu.software_equivalent(settings)
    specs = [_spec(tmp_path, index=i, colour=c)
             for i, c in enumerate(("red", "green", "blue"))]

    run = encode_segments(specs, tmp_path / "c", gpu, total_threads=4,
                          software_profile=cpu)

    assert len(run.results) == 3
    assert all(p.exists() and p.stat().st_size > 0 for p in run.clips())
    # Degrading is not "the segment failed" — the pixels are what was asked for.
    assert run.failures == []


def test_the_cpu_retry_is_announced_once_not_per_segment(tmp_path, settings, caplog):
    """Six segments failing over to the CPU is one fact, not six warnings."""
    import logging

    set_render_politeness(settings)

    gpu = _doomed_profile()
    specs = [_spec(tmp_path, index=i, duration=0.3) for i in range(6)]

    with caplog.at_level(logging.WARNING, logger="pipeline.segments"):
        encode_segments(specs, tmp_path / "c", gpu, total_threads=2,
                        software_profile=gpu.software_equivalent(settings))

    fallback_lines = [r for r in caplog.records
                      if "falling back to libx264" in r.getMessage()]
    assert len(fallback_lines) == 1, [r.getMessage() for r in fallback_lines]


def test_without_a_software_profile_a_dead_gpu_still_raises(tmp_path, settings):
    """The degrade is opt-in. A caller that did not ask for it gets the error,
    rather than silently different encoder settings."""
    set_render_politeness(settings)

    gpu = _doomed_profile()
    with pytest.raises(RenderError):
        encode_segments([_spec(tmp_path)], tmp_path / "c", gpu, total_threads=2)


# ------------------------------------------------------------------ concat


def test_concat_preserves_total_duration(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    specs = [_spec(tmp_path, index=i, duration=0.5, colour=c)
             for i, c in enumerate(("red", "green", "blue"))]
    run = encode_segments(specs, tmp_path / "c", profile, total_threads=4)
    joined = concat_clips(run.clips(), tmp_path / "joined.mp4")
    assert joined.exists()
    assert ffprobe_duration(joined) == pytest.approx(1.5, abs=0.25)


def test_concat_refuses_an_empty_list(tmp_path):
    with pytest.raises(RenderError):
        concat_clips([], tmp_path / "x.mp4")


# ------------------------------------------------------------------- cache


def test_prune_keeps_what_the_current_render_needs(tmp_path, settings):
    set_render_politeness(settings)
    profile = encode_profile(settings, "long", draft=True)
    cache = tmp_path / "c"
    specs = [_spec(tmp_path, index=i, colour=c) for i, c in
             enumerate(("red", "green", "blue", "white", "black"))]
    run = encode_segments(specs, cache, profile, total_threads=4)
    keep = {specs[0].content_hash(profile)}

    assert cache_size_mb(cache) > 0
    prune_cache(cache, keep, max_files=1)
    assert (cache / f"{specs[0].content_hash(profile)}.mp4").exists(), \
        "a hash the render still needs is never pruned"


# ------------------------------------------------- equivalence + resume
#
# These four renders are the whole cost of this module: 561 seconds, of which
# 561 are ffmpeg. Long enough that `pytest tests/` looked like it had hung,
# and a suite that looks hung is a suite nobody runs to the end — which is
# how two red tests sat unnoticed through Stage 3a.
#
# The subject here is SEGMENTATION — that the two paths agree, that the cache
# is keyed on content, that a wiped render dir resumes. None of that is a
# property of how long the narration is. So they run on the first two
# paragraphs of the fixture rather than all six: same beats, same boundaries,
# same code, a third of the audio.


@pytest.fixture(scope="module")
def short_long_text() -> str:
    """The deep-dive fixture, trimmed to the length these tests need.

    Whole paragraphs, so the tag grammar and the beat structure survive — a
    truncation mid-sentence would change what is being tested rather than
    how much of it there is.
    """
    full = (Path("fixtures/scripts/long_valid.txt")
            .read_text(encoding="utf-8"))
    paras = [p for p in full.split("\n\n") if p.strip()]
    return "\n\n".join(paras[:2])


@pytest.fixture()
def rendered_both(settings, workspace, short_long_text):
    """The fixture LONG rendered twice: segmented and single-graph."""
    from PIL import Image

    script, _ = parse_long_script(short_long_text, "EXMPL", settings)
    tts = TTSEngine(settings).synthesize(script.narration, "long")

    out = {}
    for mode in ("segmented", "single"):
        s = settings.model_copy(update={"render_segmented": mode == "segmented"})
        ws = workspace / mode
        ws.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1200, 700), (242, 242, 239)).save(
            ws / "income_statement.png")
        mp4, manifest = render_long(script, tts, ws, s, draft=True)
        out[mode] = (mp4, json.loads(Path(manifest).read_text(encoding="utf-8")))
    return out


def test_both_paths_agree_on_the_fixture(rendered_both):
    """Verify equivalence before trusting the new default."""
    seg_mp4, seg_man = rendered_both["segmented"]
    one_mp4, one_man = rendered_both["single"]

    assert seg_man["segmented"] is True and one_man["segmented"] is False
    # same beats, same boundaries, same kinds
    assert [s["kind"] for s in seg_man["segments"]] == \
        [s["kind"] for s in one_man["segments"]]
    for a, b in zip(seg_man["segments"], one_man["segments"]):
        assert a["start"] == pytest.approx(b["start"], abs=1e-6)
        assert a["end"] == pytest.approx(b["end"], abs=1e-6)
    # same resolution and the same finished length
    assert seg_man["resolution"] == one_man["resolution"]
    assert ffprobe_duration(seg_mp4) == pytest.approx(
        ffprobe_duration(one_mp4), abs=0.2)
    # and the same overlay set — the boundary-spanning furniture is unchanged
    assert {l["name"] for l in seg_man["layers"]} == \
        {l["name"] for l in one_man["layers"]}


def test_a_segmented_render_resumes_after_a_wipe(settings, workspace,
                                                 short_long_text):
    """The machine is a daily driver: losing the workspace mid-job must cost
    the segments in flight, not the whole render."""
    import shutil as _sh

    from PIL import Image

    script, _ = parse_long_script(short_long_text, "EXMPL", settings)
    Image.new("RGB", (1200, 700), (242, 242, 239)).save(
        workspace / "income_statement.png")
    tts = TTSEngine(settings).synthesize(script.narration, "long")

    mp4, man1 = render_long(script, tts, workspace, settings, draft=True)
    first = json.loads(Path(man1).read_text(encoding="utf-8"))
    assert first["segment_cache_hits"] == 0

    # simulate a reboot: the render dir is gone, the cache is not
    _sh.rmtree(workspace / "render_long_draft", ignore_errors=True)
    mp4, man2 = render_long(script, tts, workspace, settings, draft=True)
    second = json.loads(Path(man2).read_text(encoding="utf-8"))
    assert second["segment_cache_hits"] == len(second["segments"]), \
        "every completed beat survived"
    assert mp4.exists()
