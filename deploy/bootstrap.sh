#!/usr/bin/env bash
# Due Diligence Desk — headless VPS bootstrap (Ubuntu/Debian, Python 3.11+).
# Run as root from the repo checkout:  bash deploy/bootstrap.sh /opt/due-diligence-desk
set -euo pipefail

DEST="${1:-/opt/due-diligence-desk}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> apt dependencies (ffmpeg 6+, fonts, python venv)"
apt-get update -q
apt-get install -y -q ffmpeg python3.11 python3.11-venv fonts-dejavu-core
# ImageMagick is deliberately NOT required: all text/stamp rendering is
# Pillow, all animation is Pillow-frames -> ffmpeg. No display server needed.

echo "==> service user + directory"
id -u ddd &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin ddd
mkdir -p "$DEST"
if [ "$SRC" != "$DEST" ]; then
  rsync -a --delete \
    --exclude '.venv' --exclude 'workspace' --exclude 'cache' \
    --exclude 'state' --exclude '.git' \
    "$SRC/" "$DEST/"
fi
cd "$DEST"

echo "==> venv + pinned dependencies"
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -q -e .

echo "==> brand assets (deterministic, generated locally)"
.venv/bin/python scripts/gen_assets.py
.venv/bin/python scripts/gen_fixtures.py

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> wrote .env from .env.example — EDIT IT before starting:"
  echo "    TELEGRAM_BOT_TOKEN, OPERATOR_CHAT_IDS, and (when going live)"
  echo "    MOCK_MODE=false, ELEVENLABS_API_KEY, PEXELS_API_KEY, GDRIVE_*"
fi

chown -R ddd:ddd "$DEST"

echo "==> offline test suite (MOCK_MODE, zero network)"
sudo -u ddd .venv/bin/pip install -q -e '.[dev]'
sudo -u ddd .venv/bin/python -m pytest tests/ -q

echo "==> systemd units"
cp deploy/due-diligence-desk.service /etc/systemd/system/
cp deploy/due-diligence-cleanup.service /etc/systemd/system/
cp deploy/due-diligence-cleanup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable due-diligence-cleanup.timer
systemctl start due-diligence-cleanup.timer

cat <<'EOF'

Done. Next steps:
  1. edit /opt/due-diligence-desk/.env  (bot token + operator chat id)
  2. systemctl enable --now due-diligence-desk
  3. journalctl -fu due-diligence-desk
  4. message your bot: /help

Optional (large in-chat uploads): run a self-hosted Telegram Bot API
server and set TELEGRAM_API_BASE_URL — otherwise keep Google Drive
delivery (default, recommended).
EOF
