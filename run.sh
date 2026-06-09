#!/usr/bin/env bash
# Run the emoji picker from the project root.
# Usage:
#   ./run.sh          – start in background (system tray)
#   ./run.sh --show   – start and open picker immediately

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# On Wayland (KDE Plasma 6) QWidget::move() is silently ignored by the compositor.
# Running under XWayland (xcb backend) makes move() work correctly while keeping
# full clipboard and keyboard support via wl-copy / xdotool.
export QT_QPA_PLATFORM=xcb

exec "$VENV/bin/python3" "$SCRIPT_DIR/src/main.py" "$@"
