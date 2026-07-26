"""Native-Windows support: politeness knobs and portability guards.

The render box is a Windows 11 desktop used daily, running the pipeline
natively (not WSL). These tests cover the parts that are easy to regress
from a Linux dev box.
"""

from __future__ import annotations

import os
import re
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


# --------------------------------------------------------------------------
# Path portability — the repo has to CHECK OUT on Windows at all
# --------------------------------------------------------------------------
# These are not style preferences. Windows cannot create such a name, so
# `git checkout` fails on it and every file under it goes missing — while the
# Linux dev box shows a clean tree. `assets/kit/restyle/con/` (a DOS device
# name, straight out of the design kit's `con/` abbreviation) is how this was
# found: eighteen frames that only ever existed on one machine.
DOS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
WINDOWS_ILLEGAL_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')


def _windows_objection(segment: str) -> str | None:
    """Why Windows would refuse to create this path component, or None."""
    # The device name is matched on the stem, so `con.png` is as fatal as `con`.
    if segment.split(".")[0].upper() in DOS_DEVICES:
        return "reserved DOS device name"
    if segment != segment.rstrip(". "):
        return "trailing dot or space — Windows strips it, then names collide"
    if segment.startswith(" "):
        return "leading space"
    bad = "".join(sorted(set(WINDOWS_ILLEGAL_CHARS.findall(segment))))
    if bad:
        return f"illegal character(s) {bad!r}"
    return None


def _checked_out_paths() -> list[str]:
    """Every path a checkout materialises, '/'-separated.

    Tracked *and* not-yet-committed-but-not-ignored, so a bad name trips this
    guard before it is pushed — and the runtime dirs (workspace/, cache/,
    state/) stay out of it.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            capture_output=True, text=True, check=True).stdout
        return [p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        pass
    # No git (an exported tarball, say). The guard must not go quiet just
    # because it cannot ask git what is tracked.
    skip = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
            ".venv", "venv", "build", "dist", "workspace", "cache", "state", "tmp"}
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        rel = Path(dirpath).relative_to(ROOT)
        found += [(rel / f).as_posix() for f in filenames]
    return found


def test_no_path_in_the_repo_is_illegal_on_windows():
    """Permanent guard: this is a cross-platform project now."""
    paths = _checked_out_paths()
    assert len(paths) > 100, "the file listing looks wrong — the guard would pass emptily"

    offenders = [
        f"{path}  ({segment!r}: {why})"
        for path in paths
        for segment in path.split("/")
        if (why := _windows_objection(segment))
    ]
    shown = sorted(set(offenders))
    assert not offenders, (
        f"{len(offenders)} path(s) cannot be checked out on Windows:\n  "
        + "\n  ".join(shown[:20])
        + (f"\n  … and {len(shown) - 20} more" if len(shown) > 20 else ""))


def test_the_kit_export_cannot_recreate_an_illegal_name():
    """Renaming the folder is not enough — the export script made it, and
    would make it again on the next run."""
    from scripts.export_design_kit import merge_path, safe_name, safe_segment

    # The abbreviation that produced `con/`: spelled out the way the design
    # document's own section label writes it, not mechanically mangled — in
    # whatever case the id happens to use.
    assert safe_name(merge_path("restyle", "con/alert")) == "restyle/concepts/alert"
    assert safe_segment("CON") == safe_segment("Con") == "concepts"

    # Everything else Windows refuses is escaped rather than shipped.
    for bad in ("nul", "NUL", "Aux", "prn", "com1", "lpt9", "nul.png",
                "trailing.", "trailing ", " leading", 'quote"pipe|star*', "a:b"):
        assert _windows_objection(safe_segment(bad)) is None, \
            f"{bad!r} survived sanitisation as {safe_segment(bad)!r}"

    # …and a name that is already fine is left exactly alone.
    for good in ("restyle", "concepts", "hype-vs-reality", "f01", "obj-laptop_b"):
        assert safe_segment(good) == good
