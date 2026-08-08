#!/usr/bin/env bash
# Dennis - installer for the Linux target: WSL2 on the operator's desktop, or
# a bare Debian/Ubuntu VPS. Both are the same install; the differences are
# detected, not configured.
#
#   sudo bash deploy/bootstrap.sh [DEST]        # DEST defaults to /opt/dennis
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

DEST="${1:-/opt/dennis}"
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
         sudo bash deploy/bootstrap.sh ${DEST}

     uv puts the interpreter on PATH as python3.${PY_MIN_MINOR}, which this
     script then finds on its own."
fi
PY_VERSION="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
info "python: $PY ($PY_VERSION)"

# The venv package is separate on Debian/Ubuntu and its absence only shows up
# at `python -m venv`, several minutes in.
VENV_PKG="python3-venv"
case "$PY" in
  python3.1[0-9]) VENV_PKG="${PY}-venv" ;;
esac

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
step "apt dependencies (ffmpeg, fonts, python venv, rsync)"
# ImageMagick is deliberately NOT required: all text rendering is Pillow, all
# animation is Pillow-frames -> ffmpeg. No display server needed.
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ffmpeg "$VENV_PKG" fonts-dejavu-core rsync \
  || die \
"apt-get failed to install the base dependencies.

Re-run 'sudo apt-get update' and read its output - on a fresh WSL2 image this
is almost always a stale package index or no network from inside WSL."
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
# hardware encoder (informational)
# --------------------------------------------------------------------------
step "hardware encoder"
# Detection is a real smoke encode at runtime (pipeline/render_common.py), so
# this is only an early heads-up. NVENC through WSL2 works but is less
# reliable than native; the pipeline falls back to libx264 silently either way.
if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc; then
  if ffmpeg -hide_banner -loglevel error -f lavfi \
      -i color=c=black:s=128x128:d=0.1 -c:v h264_nvenc -f null - >/dev/null 2>&1; then
    ok "h264_nvenc works - finals will use the GPU"
  else
    info "h264_nvenc is listed but a smoke encode failed - finals use libx264"
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
# .env
# --------------------------------------------------------------------------
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

chown -R "$SERVICE_USER:$SERVICE_USER" "$DEST"

# --------------------------------------------------------------------------
# offline test suite
# --------------------------------------------------------------------------
step "offline test suite (MOCK_MODE, zero network)"
info "this runs real encodes and takes a while"
sudo -u "$SERVICE_USER" .venv/bin/python -m pytest tests/ -q || die \
"The offline test suite failed.

The install is otherwise complete, but do not start the bot on a red suite -
the failure above is real and reproducible with:
    cd $DEST && sudo -u $SERVICE_USER .venv/bin/python -m pytest -q"
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
cat <<'DONE'

Keep workspace/, cache/ and state/ on the Linux filesystem. Under WSL2 a path
under /mnt/c is slow enough to matter - the bot warns at startup if any of
them resolve there.

Optional (large in-chat uploads): run a self-hosted Telegram Bot API server
and set TELEGRAM_API_BASE_URL - otherwise keep Google Drive delivery
(default, recommended).
DONE
