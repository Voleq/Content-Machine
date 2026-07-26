"""Native-Windows support: politeness knobs and portability guards.

The render box is a Windows 11 desktop used daily, running the pipeline
natively (not WSL). These tests cover the parts that are easy to regress
from a Linux dev box.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from config import Settings
from pipeline.render_common import (
    _creationflags,
    _politeness_args,
    _POLITENESS,
    set_render_politeness,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_politeness():
    before = dict(_POLITENESS)
    yield
    _POLITENESS.update(before)


def test_threads_default_to_about_half_the_cores():
    s = Settings(_env_file=None)
    cores = os.cpu_count() or 4
    assert s.resolved_render_threads() == max(1, round(cores * 0.5))
    assert 1 <= s.resolved_render_threads() <= cores


def test_an_explicit_thread_count_wins_but_is_clamped():
    cores = os.cpu_count() or 4
    assert Settings(render_threads=3, _env_file=None).resolved_render_threads() == 3
    huge = Settings(render_threads=999, _env_file=None)
    assert huge.resolved_render_threads() == cores


def test_a_tiny_fraction_still_leaves_one_thread():
    s = Settings(render_thread_fraction=0.05, _env_file=None)
    assert s.resolved_render_threads() >= 1


def test_politeness_caps_the_filter_pools_too():
    """The filter graph is the bottleneck, not the encode — capping only
    -threads would leave zoompan/overlay running wide open."""
    set_render_politeness(Settings(render_threads=4, _env_file=None))
    args = _politeness_args()
    assert args.count("4") == 3
    for flag in ("-threads", "-filter_threads", "-filter_complex_threads"):
        assert flag in args


def test_no_flags_when_politeness_is_unset():
    _POLITENESS.update({"threads": 0, "below_normal": False})
    assert _politeness_args() == []


def test_below_normal_priority_is_platform_appropriate():
    set_render_politeness(Settings(render_below_normal_priority=True, _env_file=None))
    flags = _creationflags()
    if os.name == "nt":
        assert flags == subprocess.BELOW_NORMAL_PRIORITY_CLASS
    else:
        # POSIX renices after spawn instead — creationflags is a no-op there
        assert flags == 0
        assert hasattr(os, "setpriority")


def test_priority_can_be_turned_off():
    set_render_politeness(Settings(render_below_normal_priority=False, _env_file=None))
    assert _creationflags() == 0


def test_ffmpeg_runs_polite_and_still_works(tmp_path):
    """A real (tiny) encode through the polite runner."""
    from pipeline.render_common import ffprobe_duration, run_ffmpeg

    set_render_politeness(Settings(render_threads=2, _env_file=None))
    out = tmp_path / "tiny.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    assert out.exists()
    assert ffprobe_duration(out) == pytest.approx(0.3, abs=0.15)


def test_runtime_paths_are_pathlib_not_strings():
    s = Settings(_env_file=None)
    for attr in ("base_dir", "workspace_dir", "cache_dir", "state_dir",
                 "assets_dir", "templates_dir", "fixtures_dir", "fonts_dir"):
        assert isinstance(getattr(s, attr), Path), f"{attr} must be a Path"


def test_no_posix_only_separators_in_runtime_paths():
    """Anything joining paths with a literal '/' breaks on Windows."""
    import re

    offenders = []
    pattern = re.compile(r"""["'][a-zA-Z0-9_.-]+/[a-zA-Z0-9_./-]+["']""")
    for py in sorted((ROOT / "pipeline").glob("*.py")):
        for n, line in enumerate(py.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "http" in line or "https" in line:
                continue
            for m in pattern.finditer(line):
                token = m.group(0).strip("\"'")
                # kit asset NAMES are '/'-joined by design and resolved
                # through Kit.path(); mime types and format strings are fine
                if token.startswith(("image/", "video/", "text/", "application/")):
                    continue
                if "%" in token or token.endswith("/"):
                    continue
                offenders.append(f"{py.name}:{n}: {token}")
    # Kit names legitimately contain slashes; assert only that nothing looks
    # like a filesystem path with a suffix.
    real = [o for o in offenders if o.rsplit(".", 1)[-1] in
            ("png", "jpg", "json", "wav", "mp4", "mov", "ttf", "txt", "xlsx")]
    assert not real, "filesystem paths must be built with pathlib:\n" + "\n".join(real)
