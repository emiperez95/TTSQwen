#!/usr/bin/env bash
# setup-wsl.sh — Set up TTSQwen as a systemd user service inside WSL2
# Run this script inside WSL on the Windows machine.
set -euo pipefail

REPO_URL="https://github.com/emiperez95/TTSQwen.git"
PROJECT_DIR="$HOME/Projects/TTSQwen"
VENV_DIR="$PROJECT_DIR/server/.venv"
SERVICE_NAME="ttsqwen"

echo "=== TTSQwen WSL Setup ==="

# --- System dependencies ---
echo "[1/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq tmux python3-venv ffmpeg libavfilter-extra

# --- Clone repo ---
echo "[2/5] Setting up project at $PROJECT_DIR..."
mkdir -p "$(dirname "$PROJECT_DIR")"
if [ -d "$PROJECT_DIR" ]; then
    echo "  Project directory exists, pulling latest..."
    git -C "$PROJECT_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

# --- Python venv + deps ---
echo "[3/5] Creating venv and installing Python dependencies..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/server/requirements.txt"

# --- systemd user service ---
echo "[4/5] Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$PROJECT_DIR/server/ttsqwen.service" "$HOME/.config/systemd/user/${SERVICE_NAME}.service"
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"

# --- Enable lingering (service starts without login) ---
echo "[5/5] Enabling lingering and starting service..."
sudo loginctl enable-linger "$USER"
systemctl --user start "$SERVICE_NAME"

echo ""
echo "=== Setup complete ==="
echo "Service status:"
systemctl --user status "$SERVICE_NAME" --no-pager
echo ""
echo "Useful commands:"
echo "  systemctl --user status ttsqwen    # Check status"
echo "  systemctl --user restart ttsqwen   # Restart"
echo "  journalctl --user -u ttsqwen -f    # Follow logs"
echo "  curl http://localhost:9800/health   # Health check"
