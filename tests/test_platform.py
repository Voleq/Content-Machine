"""Portability guards, encode politeness, and the parked Windows scripts.

The target is Linux — WSL2 on the operator's desktop now, a Linux VPS later.
Nothing here needs Windows to run; that is the point. These guards are cheap
on Linux and they protect a move to a different filesystem later:

* the politeness knobs, which are what keep an unattended render from taking
  the desktop with it;
* the path guards, because a name Windows cannot create is a name `git
  checkout` fails on — silently, since the Linux tree still looks clean;
* the encoding guard, because an implicit text `open()` picks up whatever
  locale the host happens to have;
* the PowerShell scripts under `deploy/`, which are unmaintained but must
  still parse if anyone ever runs them.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from config import Settings
from pipeline.render_common import (
    _deprioritise,
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


def test_below_normal_priority_renices_the_spawned_child():
    """POSIX politeness is `nice`, applied to the child after it spawns.

    The Windows BELOW_NORMAL_PRIORITY_CLASS branch is gone — the target is
    Linux, and it put a Windows-only keyword argument on every ffmpeg spawn.
    """
    set_render_politeness(Settings(render_below_normal_priority=True, _env_file=None))
    assert hasattr(os, "setpriority")

    proc = subprocess.Popen(["sleep", "5"])
    try:
        _deprioritise(proc)
        assert os.getpriority(os.PRIO_PROCESS, proc.pid) == 10
    finally:
        proc.kill()
        proc.wait()


def test_priority_can_be_turned_off():
    set_render_politeness(Settings(render_below_normal_priority=False, _env_file=None))
    proc = subprocess.Popen(["sleep", "5"])
    try:
        before = os.getpriority(os.PRIO_PROCESS, proc.pid)
        _deprioritise(proc)
        assert os.getpriority(os.PRIO_PROCESS, proc.pid) == before
    finally:
        proc.kill()
        proc.wait()


def test_no_windows_only_branches_survive_in_the_runtime_path():
    """The runtime is POSIX now; a `sys.platform == "win32"` fork in the hot
    path is exactly the kind of thing that rots untested.

    `excel_refresh.py` is the deliberate exception — it is parked behind
    `excel_available()`, which the Linux flow only ever reads as False.
    """
    import io
    import tokenize

    pattern = re.compile(r"win32|BELOW_NORMAL|creationflags|os\.name")
    offenders = []
    for py in sorted((ROOT / "pipeline").glob("*.py")):
        if py.name == "excel_refresh.py":
            continue
        src = py.read_text(encoding="utf-8")
        # Only real code counts: docstrings and comments explaining why the
        # branch was removed are the whole reason this stays removed.
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if pattern.search(tok.string):
                offenders.append(f"{py.name}:{tok.start[0]}: {tok.line.strip()}")
    assert not offenders, "Windows-only branch(es) back in the runtime path:\n  " \
        + "\n  ".join(offenders)


# --------------------------------------------------------------------------
# The parked PowerShell scripts — unmaintained, but they must still PARSE
# --------------------------------------------------------------------------
# deploy/bootstrap.ps1 and deploy/install-task.ps1 are not the supported
# install path (that is deploy/bootstrap.sh under WSL2) and no test runs
# them. They are kept so a future native-Windows deployment has a starting
# point — and a script that cannot be parsed is worse than no script, because
# the failure surfaces as a syntax error on some line that looks fine.
#
# Windows PowerShell 5.1 does not assume UTF-8. A BOM-less file is decoded as
# the system ANSI codepage, so any multi-byte character — an em-dash in a
# comment is enough — arrives as mojibake and can break tokenisation. Two
# properties together avoid that: a UTF-8 BOM, and ASCII-only content so the
# encoding barely matters either way. `.gitattributes` marks *.ps1 `-text` so
# a checkout cannot strip the BOM.

PS1_SCRIPTS = ("deploy/bootstrap.ps1", "deploy/install-task.ps1")
UTF8_BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize("rel", PS1_SCRIPTS)
def test_powershell_scripts_are_ascii_with_a_bom(rel):
    raw = (ROOT / rel).read_bytes()
    assert raw.startswith(UTF8_BOM), (
        f"{rel} has no UTF-8 BOM — Windows PowerShell 5.1 would read it as the "
        f"system ANSI codepage")
    body = raw[len(UTF8_BOM):]
    assert body.isascii(), (
        f"{rel} contains non-ASCII bytes. Offending line(s): "
        + "; ".join(
            f"L{n}: {line!r}"
            for n, line in enumerate(body.decode("utf-8").splitlines(), 1)
            if not line.isascii()
        )[:400])


@pytest.mark.parametrize("rel", PS1_SCRIPTS)
def test_powershell_scripts_say_they_are_unmaintained(rel):
    """Nobody should reach for these expecting a supported path."""
    text = (ROOT / rel).read_text(encoding="utf-8-sig")
    assert "UNMAINTAINED" in text
    assert "bootstrap.sh" in text, "point the reader at the installer that is real"


@pytest.mark.parametrize("rel", PS1_SCRIPTS)
def test_powershell_scripts_have_balanced_delimiters(rel):
    """A cheap structural check — there is no PowerShell here to parse with.

    Counts braces, parens and here-strings outside of comments and strings.
    It will not catch every syntax error, but it does catch the edit that
    drops a closing brace, which is the realistic way one of these breaks
    while nobody is running it.
    """
    text = (ROOT / rel).read_text(encoding="utf-8-sig")
    # Here-strings (@"..."@) carry unbalanced braces as literal text.
    stripped = re.sub(r'@"\n.*?\n"@', '""', text, flags=re.DOTALL)
    stripped = re.sub(r"<#.*?#>", "", stripped, flags=re.DOTALL)   # block comments
    depth = {"{": 0, "(": 0}
    for line in stripped.splitlines():
        code = re.sub(r"'[^']*'", "''", line)
        code = re.sub(r'"[^"]*"', '""', code)
        code = code.split("#", 1)[0]
        depth["{"] += code.count("{") - code.count("}")
        depth["("] += code.count("(") - code.count(")")
    assert depth["{"] == 0, f"{rel}: unbalanced braces ({depth['{']:+d})"
    assert depth["("] == 0, f"{rel}: unbalanced parens ({depth['(']:+d})"


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
