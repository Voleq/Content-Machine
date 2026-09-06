#!/usr/bin/env bash
# Dennis - installer for the Linux target: WSL2 on the operator's desktop, or
# a bare Debian/Ubuntu VPS. Both are the same install; the differences are
# detected, not configured.
#
#   sudo bash deploy/bootstrap.sh [DEST] [--skip-piper]
#                                               # DEST defaults to /opt/dennis
#
# Idempotent: safe to re-run after a pull. Every step is either already-done
# or re-done cleanly.
#
# It refuses to start rather than half-install. Everything that could stop the
# run - privileges, the distro, a usable Python, FFmpeg 6+, the destination
# filesystem - is checked up front, and the run aborts with one readable
# message naming the fix. After preflight the only expected failures are a
# genuinely broken network or disk.
#
# What is REQUIRED and what is OPTIONAL is a decision made once, here: a step
# is required only if the bot cannot run without it. FFmpeg, the venv, the
# pinned dependencies, Node and the design kit are required - `render_long.py`
# calls load_plates() unguarded, so a box without assets/plates/ has a bot that
# answers /help and dies on /render. Headless Chromium (10-K screenshots) and
# the local Piper voice (free draft audio) are not - each degrades a feature
# and neither blocks a render, so each warns and the install carries on. An
# optional step that aborts leaves the operator with no service at all, which
# is strictly worse than the degradation it was trying to prevent.
#
# The kit is the step this script spent its first release missing entirely. It
# generated the placeholders (sfx, music, b-roll, memes) and then ran the test
# suite against an assets/plates/ nothing had built, so every clean install
# ended in ~180 PlateErrors under a message calling them real and reproducible.
# They were neither. Ingest is what makes the install usable, and it belongs
# before the suite that checks it.
#
# The local voice can be skipped outright, and this is honoured for real -
# unlike the message it replaces, which told the operator to set a variable
# nothing here read, in a file that did not exist yet:
#     sudo bash deploy/bootstrap.sh /opt/dennis --skip-piper
#     sudo SKIP_PIPER=1 bash deploy/bootstrap.sh /opt/dennis
# or LOCAL_TTS_ENABLED=false in an existing .env, which this now reads. The
# flag is the reliable one: `SKIP_PIPER=1 sudo bash ...` loses the variable to
# sudo's env_reset, so it has to be set on sudo's own command line (or -E).
#
# WSL2 notes:
#   * systemd is OFF by default in WSL. The service and timer install only
#     when PID 1 is systemd; otherwise the units are still copied and the
#     script prints exactly what to put in /etc/wsl.conf. Nothing silently
#     no-ops.
#   * The install destination and the runtime directories must live on the
#     Linux filesystem, never under /mnt/c. The 9p/drvfs translation layer is
#     slow for the many-small-files pattern the render cache produces, and the
#     segment cache is exactly that pattern. This is enforced, not suggested.

set -Eeuo pipefail

DEST=""
SKIP_PIPER="${SKIP_PIPER:-0}"
for arg in "$@"; do
  case "$arg" in
    --skip-piper) SKIP_PIPER=1 ;;
    -*) printf 'unknown option: %s\n\nusage: bash deploy/bootstrap.sh [DEST] [--skip-piper]\n' "$arg" >&2; exit 2 ;;
    *) [ -n "$DEST" ] || DEST="$arg" ;;
  esac
done
DEST="${DEST:-/opt/dennis}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="dennis"

# The floor is set by pyproject.toml (requires-python = ">=3.11"). The CEILING
# is set by the pinned dependency wheels: this installs exact versions, and
# pydantic-core, numpy and pillow do not publish wheels for an interpreter
# newer than the pins were cut against. A too-new Python does not fail here -
# it fails several minutes later, mid-pip, trying to build a Rust extension
# from source.
#
# Both bounds are checked BY VERSION rather than by name. Pinning python3.11
# by name made this script die on step one on Ubuntu 24.04 (ships 3.12, has no
# python3.11 package); pinning nothing made it pick up a 3.14 that cannot
# install the dependencies at all.
PY_MIN_MINOR=11
PY_MAX_MINOR=13
PYTHON_CANDIDATES=(python3.13 python3.12 python3.11 python3)
FFMPEG_MIN_MAJOR=6

# The kit engine is JS and runs at INGEST, never in the render path. The real
# floor is 16.6 - `kit/engine/plates.js` calls Array.prototype.at() - but 18 is
# the oldest release still getting security fixes and the oldest worth telling
# an operator to install, so that is what is checked.
NODE_MIN_MAJOR=18

STEP=""

# --------------------------------------------------------------------------
# output + failure
# --------------------------------------------------------------------------
if [ -t 1 ]; then
  C_STEP=$'\033[36m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'
  C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_STEP=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

step() { STEP="$1"; printf '%s==> %s%s\n' "$C_STEP" "$1" "$C_OFF"; }
info() { printf '    %s\n' "$1"; }
ok()   { printf '    %s%s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn() { printf '    %s! %s%s\n' "$C_WARN" "$1" "$C_OFF" >&2; }

die() {
  printf '\n%sFAILED%s during: %s\n' "$C_ERR" "$C_OFF" "${STEP:-preflight}" >&2
  printf '\n%s\n\n' "$1" >&2
  exit 1
}

on_err() {
  local code=$? line=$1
  printf '\n%sFAILED%s during: %s\n' "$C_ERR" "$C_OFF" "${STEP:-preflight}" >&2
  printf 'command exited %d at %s line %d\n' "$code" "${BASH_SOURCE[0]}" "$line" >&2
  printf '\nNothing further was installed. Fix the above and re-run - this\n' >&2
  printf 'script is idempotent, so completed steps will be skipped.\n\n' >&2
  exit "$code"
}
trap 'on_err $LINENO' ERR

# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------
# The invariant: whenever this script is about to run something AS the service
# user, the tree already belongs to the service user. It is called at every
# such boundary rather than once at the end, because root keeps writing into
# $DEST between them - `pip install -e` in particular recreates
# dennis.egg-info as root on every run, and the next `sudo -u` pip cannot
# os.utime() a directory it does not own:
#
#     error: Cannot update time stamp of directory 'dennis.egg-info'
#
# That failed every clean install, and chowning by hand between runs did not
# help: the next run's root-owned egg_info put it straight back. A chown that
# happens once, at the end, is a chown that happens after the damage.
#
# Cheap (a recursive chown over a venv is a second) and idempotent, so calling
# it more often than strictly needed is the right trade.
own_dest() { chown -R "$SERVICE_USER:$SERVICE_USER" "$DEST"; }

# --------------------------------------------------------------------------
# environment detection
# --------------------------------------------------------------------------
is_wsl() { [ -f /proc/sys/fs/binfmt_misc/WSLInterop ] || grep -qi microsoft /proc/version 2>/dev/null; }
has_systemd() { [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; }

# Anything under /mnt is a Windows drive seen through the translation layer.
on_windows_drive() { case "$(readlink -f "$1" 2>/dev/null || echo "$1")" in /mnt/*) return 0 ;; *) return 1 ;; esac; }

# --------------------------------------------------------------------------
# preflight - check everything BEFORE mutating anything
# --------------------------------------------------------------------------
step "preflight"

[ "$(id -u)" -eq 0 ] || die \
"This script installs system packages, a service user and systemd units, so
it needs root:

    sudo bash deploy/bootstrap.sh ${DEST}"

command -v apt-get >/dev/null 2>&1 || die \
"No apt-get. This installer targets Debian/Ubuntu (including the Ubuntu that
WSL2 installs by default). On another distro, install the equivalents by hand:
ffmpeg 6+, a Python at or above 3.11 with venv, and fonts-dejavu-core."

if is_wsl; then
  info "WSL2 detected"
  # Under WSL the repo itself is often on the Windows drive, which is the
  # single biggest performance mistake available here.
  if on_windows_drive "$SRC"; then
    warn "this checkout lives on a Windows drive ($SRC)."
    warn "Reads are slow through the translation layer. Cloning into the"
    warn "Linux filesystem (e.g. ~/Content-Machine) is much faster."
  fi
else
  info "native Linux"
fi

# The destination carries workspace/, cache/ and state/. cache/segments is
# thousands of small files that get stat'd on every render; on /mnt that is
# slow enough to change how the tool feels, so it is refused outright.
if on_windows_drive "$DEST"; then
  die \
"DEST is on a Windows drive: $DEST

workspace/, cache/ and state/ would live there. The render cache writes and
stats thousands of small files, and every one of those crosses the 9p/drvfs
translation layer - it is slow enough to be the difference between a render
finishing and a render appearing to hang.

Install to the Linux filesystem instead:

    sudo bash deploy/bootstrap.sh /opt/dennis"
fi

# A Python at or above the floor. Checked before apt so the message can name
# the real problem rather than a missing package.
PY=""
SEEN=""
for cand in "${PYTHON_CANDIDATES[@]}"; do
  command -v "$cand" >/dev/null 2>&1 || continue
  cand_ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  [ -n "$cand_ver" ] || continue
  SEEN="${SEEN}${SEEN:+, }${cand} (${cand_ver})"
  if "$cand" -c "import sys
lo, hi = ${PY_MIN_MINOR}, ${PY_MAX_MINOR}
raise SystemExit(0 if sys.version_info[0] == 3 and lo <= sys.version_info[1] <= hi else 1)" 2>/dev/null; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  die \
"No usable Python found. This needs 3.${PY_MIN_MINOR}-3.${PY_MAX_MINOR}.
Interpreters on this machine: ${SEEN:-none}

Every dependency in pyproject.toml is pinned exactly, and those pins have no
wheels for anything newer than 3.${PY_MAX_MINOR} - a newer interpreter gets
several minutes into pip and then fails compiling pydantic-core from source.

Pick whichever of these fits the machine:

  1. The distro package, if it has one in range:
         sudo apt-get install -y python3.${PY_MAX_MINOR} python3.${PY_MAX_MINOR}-venv

  2. deadsnakes, on a release old enough to have it:
         sudo add-apt-repository ppa:deadsnakes/ppa
         sudo apt-get update
         sudo apt-get install -y python3.${PY_MIN_MINOR} python3.${PY_MIN_MINOR}-venv

  3. uv - the one that always works, and the answer when the distro is too
     NEW for deadsnakes (which is the usual case on a fresh release: there is
     no PPA build for it yet, and back-version PPAs will not install):
         curl -LsSf https://astral.sh/uv/install.sh | sh
         uv python install 3.${PY_MIN_MINOR}
         sudo ln -sf \"\$(uv python find 3.${PY_MIN_MINOR})\" /usr/local/bin/python3.${PY_MIN_MINOR}
         chmod o+x ~ && chmod -R o+rX ~/.local/share/uv
         sudo bash deploy/bootstrap.sh ${DEST}

     The symlink and the chmod are not optional, and leaving them out is
     what made this route fail twice for the operator who tried it.

     The symlink: uv puts the interpreter on YOUR PATH, under ~/.local/bin.
     sudo resets PATH to the secure_path in /etc/sudoers, which does not
     contain it - so this script, running as root, finds nothing and prints
     the message you are reading now. /usr/local/bin IS on secure_path
     everywhere Debian-shaped, which is why that is the target.

     The chmod: uv keeps the interpreter under ~/.local/share/uv, and Ubuntu
     creates home directories mode 750. The ${SERVICE_USER} service user
     cannot traverse in, so the venv's bin/python is a symlink to a file it
     is not allowed to reach. This script checks that below rather than
     letting it surface three steps later as a permission error in an
     unrelated subsystem."
fi
PY_VERSION="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
info "python: $PY ($PY_VERSION)"

# Whether a venv package is needed is a question about the INTERPRETER, not
# about its name. Debian and Ubuntu are the only builds that carve ensurepip
# out into a separate package; anything from uv, pyenv or a source build
# already carries it.
#
# Deriving the package name from "$PY" got that backwards on the one route
# that needs uv. `uv python install 3.13` on a release too new for deadsnakes
# gives PY=python3.13, which named python3.13-venv - a package that cannot
# exist on a release new enough to have needed uv in the first place. apt-get
# then died on it and blamed a stale index or a broken WSL network, neither of
# which had anything to do with it.
#
# So ask the interpreter. `import venv` alone is not the question: the venv
# module is stdlib and imports fine on a Debian box with the package missing -
# it is ensurepip that gets carved out, and `python -m venv` fails on it
# several minutes in. Both are checked, because both are what venv creation
# needs.
#
# An empty VENV_PKG is the normal answer for anything not built by Debian, and
# it is left UNQUOTED at the apt-get line below so that it disappears instead
# of becoming an empty argument apt cannot parse.
if "$PY" -c 'import ensurepip, venv' 2>/dev/null; then
  VENV_PKG=""
  info "venv: built into this interpreter - no apt package needed"
else
  VENV_PKG="python3-venv"
  case "$PY" in
    python3.1[0-9]) VENV_PKG="${PY}-venv" ;;
  esac
  info "venv: not built in - apt will install $VENV_PKG"
fi

# Can $SERVICE_USER actually EXECUTE this interpreter?
#
# The venv is a set of symlinks into $PY's real location, and the bot runs as
# the service user, not as you. uv keeps its interpreters under
# ~/.local/share/uv and Ubuntu creates home directories mode 750, so a service
# user that shares no group with the operator cannot traverse in - and
# .venv/bin/python becomes a symlink to a file it is not allowed to reach.
#
# Unchecked, that surfaces three steps later as two errors that look unrelated
# and are the same cause:
#     sudo: cannot execute '$DEST/.venv/bin/piper': Permission denied (os error 13)
#     sudo: '.venv/bin/python': command not found
# The second is the misleading one - the file is right there and owned by the
# service user; sudo cannot resolve what it points AT. own_dest cannot fix it
# either, because the directory in the way is outside $DEST.
#
# BLOCKED_PATH is set to the first thing in the way, so the message can name it.
BLOCKED_PATH=""

# The others-execute bit, read rather than tested: [ -x ] is answered for root
# by root's own privileges and would say yes to a 0750 directory.
_world_x()  { local m; m="$(stat -Lc '%a' "$1" 2>/dev/null)" || return 1; [ $(( 0$m & 1 )) -ne 0 ]; }
_world_rx() { local m; m="$(stat -Lc '%a' "$1" 2>/dev/null)" || return 1; [ $(( 0$m & 5 )) -eq 5 ]; }

service_can_run() {
  BLOCKED_PATH=""
  local target real dir
  target="$1"
  # When the service user already exists (any re-run), ask the kernel rather
  # than modelling it: this accounts for groups and ACLs, which mode bits do
  # not.
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo -u "$SERVICE_USER" "$target" -c 'pass' >/dev/null 2>&1 && return 0
  fi
  # Otherwise walk it. Preflight runs before the service user is created and
  # preflight does not create things, so on a clean install this is the check
  # that runs. Group bits are not consulted: the service user is created with
  # its own group and no supplementary ones, so "other" is what applies to it.
  real="$(readlink -f "$(command -v "$target" 2>/dev/null || printf '%s' "$target")" 2>/dev/null)"
  [ -n "$real" ] || { BLOCKED_PATH="$target"; return 1; }
  _world_rx "$real" || { BLOCKED_PATH="$real"; return 1; }
  dir="$(dirname "$real")"
  while [ "$dir" != "/" ] && [ -n "$dir" ]; do
    _world_x "$dir" || { BLOCKED_PATH="$dir"; return 1; }
    dir="$(dirname "$dir")"
  done
  # The walk found nothing in the way. If the user exists, the authoritative
  # test above already disagreed, so trust that one.
  id -u "$SERVICE_USER" >/dev/null 2>&1 && return 1
  return 0
}

if ! service_can_run "$PY"; then
  die \
"$PY works for you, but the $SERVICE_USER service user cannot execute it.

In the way:  ${BLOCKED_PATH:-unknown}

The bot runs as $SERVICE_USER, and the venv about to be built here is a set of
symlinks into that interpreter's real location. A service user that cannot
traverse to it gets a venv whose bin/python resolves to nothing it may read -
which shows up later as 'Permission denied' from piper and, more confusingly,
as \"'.venv/bin/python': command not found\" for a file that is plainly there
and owned by $SERVICE_USER. Chowning $DEST cannot help: the directory in the
way is outside it.

This is the normal state of a uv-installed interpreter, because Ubuntu creates
home directories mode 750. Either open the path:

    chmod o+x ${BLOCKED_PATH:-\$HOME}

and, if the interpreter came from uv, its own tree too - as the user who ran
\`uv python install\`, not as root:

    chmod -R o+rX ~/.local/share/uv

or put an interpreter somewhere system-wide instead, which avoids the question
entirely:

    sudo apt-get install -y python3.${PY_MAX_MINOR} python3.${PY_MAX_MINOR}-venv"
fi

if has_systemd; then
  info "systemd: running as PID 1"
  SYSTEMD=1
else
  SYSTEMD=0
  if is_wsl; then
    info "systemd: not running (expected on WSL without opt-in)"
  else
    warn "systemd is not PID 1 - the service and timer will be copied, not enabled"
  fi
fi

ok "preflight passed"

# --------------------------------------------------------------------------
# apt dependencies
# --------------------------------------------------------------------------
step "apt dependencies (ffmpeg, node, git-lfs, fonts, python venv, rsync)"
# ImageMagick is deliberately NOT required: all text rendering is Pillow, all
# animation is Pillow-frames -> ffmpeg. No display server needed.
#
# espeak-ng is NOT required either, which is worth stating because Piper
# phonemises through espeak and the obvious guess is that it needs the system
# package. It does not: piper-tts 1.6.0 ships cp39-abi3 manylinux wheels
# (x86_64 and aarch64) with espeak-ng statically linked into
# piper/espeakbridge.so - ldd shows libc and nothing else - and the whole
# espeak-ng-data tree inside the package. Verified by synthesizing on a box
# with no espeak-ng, no libespeak in ldconfig and nothing on PATH: 2.9s of
# real audio. Adding it would install a package nothing links against.
#
# nodejs and npm are here because the design kit is JS: scripts/ingest_kit.py
# drives kit/engine/build.js through @resvg/resvg-js and writes the PNGs the
# renderer loads. BUILD-time only - nothing under pipeline/ shells out to node,
# and tests/test_ingest.py holds that line - but build-time on a machine with
# no node is still a machine that cannot produce artwork.
#
# git-lfs is here because samples/*.mp4 are LFS objects. A clone without it
# gets 132-byte pointer files, and the fifteen tests in test_short_holds.py
# fail on `moov atom not found` - which reads like a broken ffmpeg and is
# actually a missing prerequisite nothing had named.
#
# $VENV_PKG is deliberately UNQUOTED: it is empty for any interpreter that
# carries ensurepip itself, and an empty quoted argument is one apt-get
# rejects. This is the one place in this script where the missing quotes are
# the point.
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# shellcheck disable=SC2086  # $VENV_PKG must word-split away when empty
apt-get install -y -q ffmpeg nodejs npm git-lfs fonts-dejavu-core rsync $VENV_PKG \
  || die \
"apt-get failed to install the base dependencies.

Re-run 'sudo apt-get update' and read its output - on a fresh WSL2 image this
is almost always a stale package index or no network from inside WSL.

If it named a package rather than the network - a python3.NN-venv that does
not exist, say - that is a bug in this script and worth reporting: the venv
package is chosen from what the interpreter actually carries, not from its
name, precisely so it cannot ask for one that was never published."
ok "installed"

# --------------------------------------------------------------------------
# ffmpeg 6+
# --------------------------------------------------------------------------
step "FFmpeg ${FFMPEG_MIN_MAJOR}+"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg is still not on PATH after apt-get install."
command -v ffprobe >/dev/null 2>&1 || die "ffprobe is missing (it ships with ffmpeg - is this a partial install?)"

FFMPEG_VERSION="$(ffmpeg -hide_banner -version 2>/dev/null | head -1 | awk '{print $3}')"
FFMPEG_MAJOR="$(printf '%s' "$FFMPEG_VERSION" | sed 's/[^0-9].*//')"
if [ -z "$FFMPEG_MAJOR" ] || [ "$FFMPEG_MAJOR" -lt "$FFMPEG_MIN_MAJOR" ] 2>/dev/null; then
  die \
"FFmpeg ${FFMPEG_MIN_MAJOR}+ is required; this is '${FFMPEG_VERSION:-unknown}'.

The renderer uses filters and encoder options that older builds do not have,
so this would fail mid-render rather than at startup. On a release that ships
something older, take it from a backport or a static build."
fi
ok "ffmpeg $FFMPEG_VERSION"

# --------------------------------------------------------------------------
# Node - the kit engine
# --------------------------------------------------------------------------
step "Node ${NODE_MIN_MAJOR}+ (the design kit's engine)"
# REQUIRED, at build time. The kit is code: kit/engine/build.js declares every
# plate as an author plus a seed, scripts/ingest_kit.py runs it through
# @resvg/resvg-js and writes the PNGs, and the render path then loads plain
# files with no node anywhere near it. Skip this and assets/plates/ is never
# built, which is a bot that answers /help and dies on /render.
command -v node >/dev/null 2>&1 || die \
"node is still not on PATH after apt-get install.

The design kit is JavaScript and is rendered to PNGs at ingest. Without node
there is no artwork, and the renderer has nothing to load."

command -v npm >/dev/null 2>&1 || die \
"npm is missing (it ships alongside nodejs on Debian/Ubuntu).

    sudo apt-get install -y npm"

NODE_VERSION="$(node --version 2>/dev/null | sed 's/^v//')"
NODE_MAJOR="$(printf '%s' "$NODE_VERSION" | sed 's/[^0-9].*//')"
if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt "$NODE_MIN_MAJOR" ] 2>/dev/null; then
  die \
"Node ${NODE_MIN_MAJOR}+ is required; this is '${NODE_VERSION:-unknown}'.

Ubuntu 22.04 still ships Node 12 in its own repository, which is the usual way
to land here. The engine needs newer syntax than that (Array.prototype.at, for
one), so this would fail inside the kit build rather than at startup.

Take a current release from NodeSource:

    curl -fsSL https://deb.nodesource.com/setup_${NODE_MIN_MAJOR}.x | sudo -E bash -
    sudo apt-get install -y nodejs

then re-run this script."
fi
ok "node $NODE_VERSION"

# --------------------------------------------------------------------------
# Git LFS media
# --------------------------------------------------------------------------
step "Git LFS media (samples/)"
# samples/*.mp4 are LFS objects (see .gitattributes). A clone made on a box
# without git-lfs gets 132-byte pointer files instead, and the fifteen tests in
# test_short_holds.py - which discover the samples from the directory rather
# than by name - fail on `moov atom not found` and
# `could not convert string to float: ''`. Those read like a broken ffmpeg and
# are nothing of the sort.
#
# This has to happen in $SRC, before the rsync: $DEST gets no .git (it is
# excluded), so `git lfs pull` there has nothing to resolve against. Fixing it
# after the copy is not possible, which is why it is fixed before.

# No pipeline here on purpose: `head -c 64 | grep -q` is a pipefail trap - grep
# exits on the first match and SIGPIPEs head, so the pipeline reports failure
# for the pointer it just matched.
lfs_pointer() {
  [ -f "$1" ] || return 1
  case "$(head -c 64 "$1" 2>/dev/null)" in
    *git-lfs.github.com/spec*) return 0 ;;
    *) return 1 ;;
  esac
}

# The checkout belongs to the operator, not to root, so run git as them where
# we can and disarm the dubious-ownership refusal where we cannot.
git_src() {
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    sudo -u "$SUDO_USER" -H git -C "$SRC" -c safe.directory="$SRC" "$@"
  else
    git -C "$SRC" -c safe.directory="$SRC" "$@"
  fi
}

LFS_POINTERS=0
# Set when this run knows the samples are still pointers. The test suite's
# failure message reads it, so that a red suite names the cause this run
# already found instead of insisting the failure is the operator's to debug.
LFS_DEGRADED=0
for f in "$SRC"/samples/*.mp4; do
  if lfs_pointer "$f"; then LFS_POINTERS=1; break; fi
done

if [ "$LFS_POINTERS" -eq 0 ]; then
  info "samples are real media - nothing to fetch"
elif ! git_src rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  LFS_DEGRADED=1
  warn "$SRC/samples holds LFS pointer files and is not a git checkout, so"
  warn "there is nothing here to resolve them against. The fifteen sample"
  warn "measurements in tests/test_short_holds.py will fail below."
  warn "Clone the repository with git-lfs installed and re-run."
else
  info "samples are LFS pointers - fetching the real media"
  if git_src lfs install --local >/dev/null 2>&1 && git_src lfs pull; then
    ok "LFS media fetched into $SRC"
  else
    LFS_DEGRADED=1
    warn "git lfs pull failed. samples/*.mp4 are still 132-byte pointers, and"
    warn "the fifteen tests in tests/test_short_holds.py will fail below on"
    warn "'moov atom not found' - which is this, not a broken ffmpeg. Retry:"
    warn "    cd $SRC && git lfs install && git lfs pull"
  fi
fi

# --------------------------------------------------------------------------
# hardware encoder (informational)
# --------------------------------------------------------------------------
step "hardware encoder"
# Detection is a real smoke encode at runtime (pipeline/render_common.py), so
# this is only an early heads-up. NVENC through WSL2 works but is less
# reliable than native; the pipeline falls back to libx264 silently either way.
# The probe frame is 640x360, not 128x128. NVENC has a minimum frame dimension
# and a current driver refuses anything under it outright:
#     [h264_nvenc] InitializeEncoder failed: invalid param (8):
#                  Frame Dimension less than the minimum supported value.
# So the old probe reported "no GPU" on a working RTX 3060 with the driver
# loaded, and every render on that box fell back to libx264 while the card sat
# idle. 640x360 is still instant and is a size any encoder will take.
if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc; then
  if nvenc_err="$(ffmpeg -hide_banner -loglevel error -f lavfi \
      -i color=c=black:s=640x360:d=0.1 -c:v h264_nvenc -f null - 2>&1 >/dev/null)"; then
    ok "h264_nvenc works - finals will use the GPU"
  else
    info "h264_nvenc is listed but a smoke encode failed - finals use libx264"
    # The reason, not just the verdict. "listed but failed" reads as "no GPU"
    # and closes the investigation; the actual line from the encoder is what
    # tells a driver problem apart from a probe this script got wrong.
    if [ -n "$nvenc_err" ]; then
      while IFS= read -r nvenc_line; do
        [ -n "$nvenc_line" ] && info "  $nvenc_line"
      done <<< "$(printf '%s' "$nvenc_err" | tail -n 5)"
    fi
    is_wsl && info "(common under WSL2; the fallback is automatic and silent)"
  fi
else
  info "no NVENC - finals use libx264 (fine, just slower)"
fi

# --------------------------------------------------------------------------
# service user + destination
# --------------------------------------------------------------------------
step "service user + directory"
id -u "$SERVICE_USER" >/dev/null 2>&1 \
  || useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$DEST"
if [ "$SRC" != "$DEST" ]; then
  rsync -a --delete \
    --exclude '.venv' --exclude 'workspace' --exclude 'cache' \
    --exclude 'state' --exclude '.git' \
    "$SRC/" "$DEST/"
fi
cd "$DEST"
own_dest
ok "$DEST"

# --------------------------------------------------------------------------
# venv + pinned dependencies
# --------------------------------------------------------------------------
step "venv + pinned dependencies"
# Idempotent: an existing venv whose interpreter still works is reused. A
# broken one (deleted system python, half-created) is rebuilt rather than
# limped along.
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys' 2>/dev/null; then
  info "reusing the existing venv"
else
  [ -e .venv ] && { info "existing venv is broken - rebuilding"; rm -rf .venv; }
  "$PY" -m venv .venv || die \
"Could not create the virtualenv with $PY.

The venv module ships separately on Debian/Ubuntu:
    sudo apt-get install -y $VENV_PKG"
fi
.venv/bin/pip install --upgrade pip -q
# Everything comes from the pinned pyproject.toml. `filings` pulls Playwright
# and BeautifulSoup for the 10-K screenshots; `dev` pulls pytest for the
# offline suite below.
.venv/bin/pip install -q -e '.[dev,filings]' || die \
"Dependency install failed.

Every version in pyproject.toml is pinned, so this is a network problem or a
version that has been yanked - the pip output above says which."

# The exact form of the preflight check, now that the service user exists and
# there is a real venv to point at. Preflight had to model the answer by
# reading mode bits; this asks the kernel, which also accounts for groups and
# ACLs. Everything after this line runs `sudo -u $SERVICE_USER .venv/bin/...`,
# so this is the last moment the failure can still be explained.
own_dest
if ! service_can_run "$DEST/.venv/bin/python"; then
  die \
"The venv is built, but $SERVICE_USER cannot execute $DEST/.venv/bin/python.

In the way:  ${BLOCKED_PATH:-$PY}

.venv/bin/python is a symlink to $PY, and the service user has to be able to
follow it. It cannot, so every step below - the kit build, the Piper smoke
test, the test suite, and eventually the service itself - would fail on a file
that is plainly present and owned by $SERVICE_USER:

    sudo: '.venv/bin/python': command not found

Open the path to the interpreter:

    chmod o+x ${BLOCKED_PATH:-$(dirname "$(readlink -f "$PY")")}

or install one somewhere system-wide, which avoids the question entirely:

    sudo apt-get install -y python3.${PY_MAX_MINOR} python3.${PY_MAX_MINOR}-venv"
fi
ok "installed from the pinned pyproject.toml"

# --------------------------------------------------------------------------
# headless Chromium
# --------------------------------------------------------------------------
step "headless Chromium + system libraries (Playwright)"
# The filings feature snaps 10-K excerpts with headless Chromium.
# `install --with-deps` pulls the browser AND its apt libraries (libnss3,
# libgbm, libatk, fonts...), which is the part that is easy to miss on a
# minimal WSL2 image. OPTIONAL: without it the pull degrades to zero
# auto-shots and a render is never blocked, so this warns and carries on.
if .venv/bin/playwright install --with-deps chromium; then
  ok "chromium ready"
else
  warn "Chromium install failed. 10-K auto-screenshots will degrade to none;"
  warn "renders are NOT blocked by this. Retry later with:"
  warn "    $DEST/.venv/bin/playwright install --with-deps chromium"
fi

# --------------------------------------------------------------------------
# generated assets
# --------------------------------------------------------------------------
step "brand assets + fixtures (deterministic, generated locally)"
.venv/bin/python scripts/gen_assets.py
.venv/bin/python scripts/gen_fixtures.py
ok "generated"

# --------------------------------------------------------------------------
# the design kit
# --------------------------------------------------------------------------
step "design kit (the node engine -> assets/plates)"
# REQUIRED, and the step this installer used to leave out altogether. gen_assets
# above draws placeholders for everything the kit does NOT draw - sfx, music,
# b-roll, memes - and nothing at all for the 143 plates, because those are the
# kit's. Without this step assets/plates/ never exists, load_plates() raises
# PlateError, and the test suite below reports ~180 failures under a message
# calling them real and reproducible. They were an installer that skipped its
# own build.
#
# Deliberately NOT cached across runs. `ingest_kit.py --check` verifies the
# artwork on disk against its own registry, not against kit/, so a kit that
# changed in a `git pull` would pass a check and ship stale plates. The
# day-to-day update command is `git pull && sudo bash deploy/bootstrap.sh`, so
# rebuilding every time is what keeps the artwork and the code the same age.
npm ci --no-audit --no-fund || die \
"npm ci failed, so the kit's rasteriser (@resvg/resvg-js) is not installed.

It is a BUILD-time dependency only - the render path loads PNGs and never
touches node - but without it there is no artwork to load. This is a network
problem or a registry problem; the npm output above says which. Retry alone:
    cd $DEST && npm ci"

.venv/bin/python scripts/ingest_kit.py kit || die \
"The design kit did not build.

The engine runs kit/engine/build.js and reconciles what it emits against the
manifests the artwork was signed off against; it refuses to install anything
the two disagree about, so a failure here is a real disagreement rather than a
flaky step. The output above names it. Nothing was installed into
assets/plates/, and the test suite below would report every plate as missing."
own_dest
ok "kit installed into $DEST/assets/plates"

# --------------------------------------------------------------------------
# .env
# --------------------------------------------------------------------------
# Before the voice step, not after it: the voice step READS this file for the
# operator's LOCAL_TTS_ENABLED switch, and WRITES back what it actually
# managed to verify. Neither is possible while .env is created afterwards -
# which is why the old "set LOCAL_TTS_ENABLED=false and re-run" instruction
# could not work on a clean install: at that point there was no .env to set it
# in, and nothing here read it if there had been.
step ".env"
if [ ! -f .env ]; then
  cp .env.example .env
  info "wrote .env from .env.example - EDIT IT before starting:"
  info "  TELEGRAM_BOT_TOKEN, OPERATOR_CHAT_IDS, and (when going live)"
  info "  MOCK_MODE=false, ELEVENLABS_API_KEY + the Dennis voice id,"
  info "  PEXELS_API_KEY, GDRIVE_*, SEC_USER_AGENT (required for 10-K"
  info "  pulls), GITHUB_MODELS_TOKEN (free-tier quote flagging)"
else
  info ".env already exists - left alone"
fi

# key=value in .env, whether the key is absent, blank or already set.
env_set() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
# A key set to one of the falsey spellings pydantic-settings accepts.
env_off() { grep -qiE "^$1=[[:space:]]*(false|0|no|off)[[:space:]]*$" .env; }

# --------------------------------------------------------------------------
# local neural voice (Piper) - the free tier
# --------------------------------------------------------------------------
# This is what makes /proof and /draft free AND listenable. Without it
# tier_for() falls back to the mock hum, which reports success and delivers a
# tone - a tier that is configured but non-functional is worse than one that
# is absent, so this step VERIFIES with a real synthesis rather than trusting
# that pip exited 0. Same principle as the NVENC probe above: believe the
# artefact, not the feature list.
#
# OPTIONAL, and every failure below is a warning. tier_for() falls back
# mock -> local -> paid and can never escalate a draft to a paid generation,
# so an absent voice costs audio quality and exactly $0. Aborting here used to
# take the test suite and the systemd units with it: a box that could not
# install Piper got no bot at all, and was told "everything else is already
# installed", which was not true - the service did not exist.
step "local neural voice (Piper) - the free draft/proof tier"
PIPER_VOICE="en_GB-northern_english_male-medium"
PIPER_DIR="$DEST/assets/voices"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/$PIPER_VOICE"
PIPER_MODEL_PATH="$PIPER_DIR/$PIPER_VOICE.onnx"
PIPER_BIN="$DEST/.venv/bin/piper"
PIPER_OK=0
# Skipped and failed are different answers, and .env is edited on only one of
# them: a skipped run must leave a voice an earlier run proved working exactly
# where it is. "Do not spend two minutes on this" is not "throw away my voice".
PIPER_TRIED=0

# One place to say what the loss is, so all three failure paths say the same
# true thing and name a retry that exists.
piper_degraded() {
  warn ""
  warn "The free local voice is NOT installed. This is a degradation, not a"
  warn "blocked install: /draft and /proof still work and still cost \$0 - they"
  warn "fall back to the mock hum, a tone rather than the script, and the bot"
  warn "labels the tier so you can tell. A final still buys one ElevenLabs"
  warn "generation exactly as before; a missing local voice can never escalate"
  warn "a draft to a paid one. Re-run this script to retry it - it is"
  warn "idempotent, so the steps that already succeeded are skipped:"
  warn "    sudo bash $SRC/deploy/bootstrap.sh $DEST"
  warn "Add --skip-piper to stop it trying at all."
}

if [ "$SKIP_PIPER" = "1" ]; then
  info "skipped (--skip-piper / SKIP_PIPER=1)"
  info "/draft and /proof will use the mock hum."
elif env_off LOCAL_TTS_ENABLED; then
  info "skipped: LOCAL_TTS_ENABLED is off in $DEST/.env"
  info "Set it back to true and re-run to install the free voice."
else
  PIPER_TRIED=1
  # Root, like every other install step. This ran under `sudo -u` before,
  # which is what made a clean install impossible: root's `pip install -e`
  # above leaves a root-owned dennis.egg-info, and the service user's pip then
  # cannot touch it. The venv belongs to the install phase, and the install
  # phase is root's; own_dest hands the result over.
  if .venv/bin/pip install -q -e '.[voice]'; then
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$PIPER_DIR"
    PIPER_MODELS_OK=1
    for suffix in .onnx .onnx.json; do
      target="$PIPER_DIR/$PIPER_VOICE$suffix"
      if [ -s "$target" ]; then
        info "$PIPER_VOICE$suffix already present"
        continue
      fi
      info "downloading $PIPER_VOICE$suffix"
      if ! curl -sSfL -o "$target" "$PIPER_BASE$suffix"; then
        rm -f "$target"   # a partial download is worse than none
        PIPER_MODELS_OK=0
        warn "could not download $PIPER_BASE$suffix"
        break
      fi
    done

    if [ "$PIPER_MODELS_OK" -eq 1 ]; then
      # The smoke test. A model file that exists proves nothing: it can be a
      # truncated download, the wrong architecture, or a voice this build of
      # piper cannot load. Synthesize a real sentence and require real audio.
      #
      # It runs as $SERVICE_USER on purpose - that is the user systemd will
      # run the bot as, so this also proves that user can execute the venv and
      # read the model. Which makes the output directory part of the test:
      # `mktemp -d` returns a 0700 root-owned directory that the service user
      # cannot write, so piper died with PermissionError before it ever
      # reached the model. The old `>/dev/null 2>&1` then swallowed the
      # traceback and reported "no usable audio" - a true statement about the
      # symptom that named none of the cause.
      own_dest
      PIPER_SMOKE_DIR="$(mktemp -d)"
      chown "$SERVICE_USER:$SERVICE_USER" "$PIPER_SMOKE_DIR"
      PIPER_SMOKE="$PIPER_SMOKE_DIR/smoke.wav"
      PIPER_LOG="$PIPER_SMOKE_DIR/piper.log"

      # stderr is captured, never discarded, so a failure prints the reason it
      # actually hit instead of making the operator rebuild the command by
      # hand. Captured beats re-running: it is the output of the run that
      # failed, not of a second attempt that may not fail the same way.
      # (The redirect is root's, not sudo's - which is what we want: the log
      # is written by the shell that has to read it back.)
      if echo "Noise, or signal? We are about to find out." \
          | sudo -u "$SERVICE_USER" "$PIPER_BIN" \
              -m "$PIPER_MODEL_PATH" -f "$PIPER_SMOKE" >"$PIPER_LOG" 2>&1 \
         && [ -s "$PIPER_SMOKE" ] \
         && [ "$(ffprobe -v error -show_entries format=duration -of csv=p=0 \
                  "$PIPER_SMOKE" 2>/dev/null | cut -d. -f1)" -ge 1 ] 2>/dev/null; then
        PIPER_OK=1
        ok "Piper speaks - /draft and /proof get a real voice for \$0"
      else
        warn "Piper is installed and the voice model is present, but"
        warn "synthesizing a test sentence produced no usable audio."
        warn ""
        warn "piper said:"
        if [ -s "$PIPER_LOG" ]; then
          while IFS= read -r piper_line; do
            warn "  $piper_line"
          done < <(tail -n 20 "$PIPER_LOG")
        else
          warn "  (nothing on stdout or stderr)"
        fi
        warn ""
        warn "Reproduce it the way it runs - as $SERVICE_USER, into a"
        warn "directory that user can write:"
        warn "    d=\$(mktemp -d) && chown $SERVICE_USER \"\$d\" && echo hello |"
        warn "    sudo -u $SERVICE_USER $PIPER_BIN -m $PIPER_MODEL_PATH -f \"\$d/t.wav\""
        piper_degraded
      fi
      rm -rf "$PIPER_SMOKE_DIR"
    else
      warn "The voice model did not download, so there is nothing to speak with."
      piper_degraded
    fi
  else
    warn "Could not install the pinned piper-tts into the venv (see pip above)."
    warn "Retry that step alone with:"
    warn "    cd $DEST && sudo .venv/bin/pip install -e '.[voice]'"
    piper_degraded
  fi
fi

# The .env now describes what was verified, not what was intended.
#
# LOCAL_TTS_BINARY and LOCAL_TTS_MODEL are the two settings the operator
# cannot be expected to know. The model is an absolute path to a file this
# script just downloaded. The binary is subtler: available() resolves it with
# shutil.which(), the unit runs .venv/bin/python directly, and systemd's
# default PATH does not contain .venv/bin - so the bare default "piper" is not
# findable under the service even when Piper is installed and perfect, and
# every /draft quietly gets the hum despite a working voice. An absolute path
# is what which() needs, and it is the same class of setting as the model:
# knowable only from here.
#
# Written only when the smoke test passed. Left blank otherwise, which is the
# difference between a draft that falls back to the mock hum and one that
# fails mid-render: available() reports "not set", tier_for() resolves to
# mock, and the operator gets the hum they were warned about. A setting that
# claims a voice this run could not demonstrate is exactly the lie the smoke
# test exists to catch.
if [ "$PIPER_OK" -eq 1 ]; then
  if grep -qE '^LOCAL_TTS_MODEL=.+' .env; then
    info "LOCAL_TTS_MODEL already set - left alone"
  else
    env_set LOCAL_TTS_MODEL "$PIPER_MODEL_PATH"
    ok "LOCAL_TTS_MODEL -> $PIPER_MODEL_PATH"
  fi
  if grep -qE '^LOCAL_TTS_BINARY=[[:space:]]*(piper)?[[:space:]]*$' .env \
     || ! grep -q '^LOCAL_TTS_BINARY=' .env; then
    env_set LOCAL_TTS_BINARY "$PIPER_BIN"
    ok "LOCAL_TTS_BINARY -> $PIPER_BIN"
  else
    info "LOCAL_TTS_BINARY already set - left alone"
  fi
elif [ "$PIPER_TRIED" -eq 1 ] \
     && grep -qE "^LOCAL_TTS_MODEL=[[:space:]]*${PIPER_MODEL_PATH}[[:space:]]*$" .env; then
  # It points at a voice this run tried and could not demonstrate. Blank it
  # rather than leave a config promising a tier the box cannot deliver. A model
  # path the operator chose is theirs, and is left alone.
  env_set LOCAL_TTS_MODEL ""
  warn "LOCAL_TTS_MODEL cleared - drafts fall back to the mock hum until the"
  warn "voice installs cleanly."
fi

own_dest

# --------------------------------------------------------------------------
# offline test suite
# --------------------------------------------------------------------------
step "offline test suite (MOCK_MODE, zero network)"
info "this runs real encodes and takes a while"
# This runs AFTER the kit, which is the whole point of where it sits. It used
# to run against an assets/plates/ that nothing in this script ever built, so
# every clean install ended in ~180 PlateErrors below a message calling them
# real and reproducible - the one sentence guaranteed to stop a first-time
# installer, and the only one in the run that was false.
#
# The message may only claim a failure is the operator's to debug when this
# run has nothing of its own to blame. Where it does, it says so first.
if ! sudo -u "$SERVICE_USER" .venv/bin/python -m pytest tests/ -q; then
  if [ "$LFS_DEGRADED" -eq 1 ]; then
    die \
"The offline test suite failed, and this run already knows why.

samples/*.mp4 are still Git LFS pointer files - see the warning further up.
The fifteen tests in tests/test_short_holds.py measure those samples frame by
frame, so against a 132-byte pointer they fail on 'moov atom not found' and
'could not convert string to float' - which look like a broken ffmpeg and are
not. Fetch the media and re-run this script:

    cd $SRC && git lfs install && git lfs pull
    sudo bash $SRC/deploy/bootstrap.sh $DEST

If there are failures ABOVE and BEYOND those fifteen, they are real."
  fi
  # Nothing this run did explains it, so it is the operator's to debug.
  die \
"The offline test suite failed.

The install is otherwise complete, but do not start the bot on a red suite -
the failure above is real and reproducible with:
    cd $DEST && sudo -u $SERVICE_USER .venv/bin/python -m pytest -q"
fi
ok "suite green"

# --------------------------------------------------------------------------
# systemd units
# --------------------------------------------------------------------------
step "systemd units"
install -m 0644 deploy/dennis.service /etc/systemd/system/
install -m 0644 deploy/dennis-cleanup.service /etc/systemd/system/
install -m 0644 deploy/dennis-cleanup.timer /etc/systemd/system/

if [ "$SYSTEMD" -eq 1 ]; then
  systemctl daemon-reload
  systemctl enable dennis-cleanup.timer
  systemctl start dennis-cleanup.timer
  ok "units installed; cleanup timer enabled"
  UNITS_LIVE=1
else
  UNITS_LIVE=0
  warn "units copied to /etc/systemd/system but NOT enabled: systemd is not PID 1."
  if is_wsl; then
    warn ""
    warn "WSL does not run systemd unless you opt in. Add this to /etc/wsl.conf:"
    warn ""
    warn "    [boot]"
    warn "    systemd=true"
    warn ""
    warn "then, from Windows, restart the distro:  wsl --shutdown"
    warn "Re-run this script afterwards and the units will enable."
  fi
fi

# --------------------------------------------------------------------------
# done
# --------------------------------------------------------------------------
printf '\n%sDone.%s Next steps:\n\n' "$C_OK" "$C_OFF"
echo "  1. edit $DEST/.env  (bot token + operator chat id)"
if [ "$UNITS_LIVE" -eq 1 ]; then
  echo "  2. systemctl enable --now dennis"
  echo "  3. journalctl -fu dennis"
  echo "  4. message your bot: /help"
else
  echo "  2. enable systemd (above), re-run this script, then:"
  echo "         systemctl enable --now dennis"
  echo "     or just run it in the foreground:"
  echo "         cd $DEST && sudo -u $SERVICE_USER .venv/bin/python main.py"
  echo "  3. message your bot: /help"
fi

# The install is done either way, so the last word says which install it is.
# An operator who scrolled past one warning fifty lines up should not have to
# discover from the audio that the free voice never got installed.
printf '\n'
if [ "$PIPER_OK" -eq 1 ]; then
  echo "  free draft voice: INSTALLED (/draft and /proof speak, \$0)"
elif [ "$PIPER_TRIED" -eq 0 ]; then
  echo "  free draft voice: SKIPPED - not touched this run, so whatever"
  echo "  LOCAL_TTS_* already says in .env still stands."
else
  echo "  free draft voice: ABSENT - /draft and /proof fall back to the mock"
  echo "  hum (a tone, not the script). Everything else above is installed and"
  echo "  the bot runs. Finals are unaffected; nothing costs more because of"
  echo "  this. Re-run this script to retry the voice."
fi
cat <<'DONE'

Keep workspace/, cache/ and state/ on the Linux filesystem. Under WSL2 a path
under /mnt/c is slow enough to matter - the bot warns at startup if any of
them resolve there.

Optional (large in-chat uploads): run a self-hosted Telegram Bot API server
and set TELEGRAM_API_BASE_URL - otherwise keep Google Drive delivery
(default, recommended).
DONE
