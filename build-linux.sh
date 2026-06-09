#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="MojiTap"
BUILD_VENV="$SCRIPT_DIR/.venv-build"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
SPEC_FILE="$SCRIPT_DIR/${APP_NAME}.spec"
ICON_FILE="$SCRIPT_DIR/assets/app_icon.png"
USER_APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
USER_ICONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
DESKTOP_FILE_NAME="${APP_NAME}.desktop"
INSTALLED_ICON_NAME="mojitap.png"

if [[ "${OSTYPE:-}" != linux* ]]; then
    echo "This build script is intended for Linux only." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to build ${APP_NAME}." >&2
    exit 1
fi

if [[ ! -f "$ICON_FILE" ]]; then
    echo "Missing icon file: $ICON_FILE" >&2
    exit 1
fi

if [[ ! -d "$BUILD_VENV" ]]; then
    echo "[build] Creating build virtual environment at $BUILD_VENV"
    python3 -m venv "$BUILD_VENV"
fi

# shellcheck disable=SC1091
source "$BUILD_VENV/bin/activate"

echo "[build] Installing/updating build dependencies"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r "$SCRIPT_DIR/requirements.txt" pyinstaller

echo "[build] Cleaning previous build artifacts"
rm -rf "$BUILD_DIR" "$DIST_DIR" "$SPEC_FILE"

# Match the normal Linux runtime behavior used by run.sh / main.py
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

echo "[build] Building onefile executable"
python -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    --paths "$SCRIPT_DIR/src" \
    --add-data "$ICON_FILE:assets" \
    --collect-all emoji \
    --collect-submodules pynput \
    "$SCRIPT_DIR/src/main.py"

cp "$ICON_FILE" "$DIST_DIR/app_icon.png"

cat > "$DIST_DIR/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Name=MojiTap
Exec=$DIST_DIR/$APP_NAME
Icon=$DIST_DIR/app_icon.png
Type=Application
Categories=Utility;
Comment=Emoji picker with global hotkey
Terminal=false
EOF

install_to_applications_menu() {
    local desktop_target="$USER_APPS_DIR/$DESKTOP_FILE_NAME"
    local icon_target="$USER_ICONS_DIR/$INSTALLED_ICON_NAME"

    mkdir -p "$USER_APPS_DIR" "$USER_ICONS_DIR"
    cp "$ICON_FILE" "$icon_target"

    cat > "$desktop_target" <<EOF
[Desktop Entry]
Name=MojiTap
Exec=$DIST_DIR/$APP_NAME
Icon=$icon_target
Type=Application
Categories=Utility;
Comment=Emoji picker with global hotkey
Terminal=false
EOF

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
    fi

    echo "[build] Installed launcher: $desktop_target"
    echo "[build] Installed icon: $icon_target"
}

if [[ -t 0 ]]; then
    printf "Add to system applications? [y/N] "
    read -r add_to_apps
    case "$add_to_apps" in
        [yY]|[yY][eE][sS])
            install_to_applications_menu
            ;;
        *)
            echo "[build] Skipped applications menu install"
            ;;
    esac
else
    echo "[build] Non-interactive shell detected; skipping applications menu install prompt"
fi

echo "[build] Done"
echo "[build] Executable: $DIST_DIR/$APP_NAME"
echo "[build] Desktop launcher: $DIST_DIR/${APP_NAME}.desktop"
