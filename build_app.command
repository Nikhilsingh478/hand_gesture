#!/bin/bash
# -------------------------------------------------------
#  Build Hand Scroll Controller.app
#  Double-click this file to build the Mac app bundle.
# -------------------------------------------------------
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ""
echo "================================================"
echo "  Building Hand Scroll Controller.app"
echo "  This takes 3-5 minutes. Please wait..."
echo "================================================"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "Python 3 not found" message "Please install Python 3 from https://python.org and try again."'
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Using Python $PYTHON_VERSION"

# Create / reuse a build-only virtual environment
if [ ! -d "build_venv" ]; then
    echo "Creating build environment..."
    python3 -m venv build_venv
fi
source build_venv/bin/activate

echo "Installing dependencies (may take a few minutes on first run)..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install "pyinstaller>=6.0" --quiet

echo ""
echo "Running PyInstaller..."
echo ""

pyinstaller \
    --noconfirm \
    --windowed \
    --name "Hand Scroll Controller" \
    --collect-all mediapipe \
    --collect-all cv2 \
    --hidden-import pyautogui \
    --hidden-import numpy \
    --hidden-import AppKit \
    --osx-bundle-identifier "com.handscroll.controller" \
    main.py

APP_SRC="$DIR/dist/Hand Scroll Controller.app"
PLIST="$APP_SRC/Contents/Info.plist"

# Inject camera permission description so macOS grants access
if [ -f "$PLIST" ]; then
    /usr/libexec/PlistBuddy -c \
        "Add :NSCameraUsageDescription string 'Hand Scroll Controller uses your camera to detect hand gestures for scrolling.'" \
        "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c \
        "Set :NSCameraUsageDescription 'Hand Scroll Controller uses your camera to detect hand gestures for scrolling.'" \
        "$PLIST"
    echo "Camera permission description added to Info.plist."
fi

DESKTOP="$HOME/Desktop"
DEST="$DESKTOP/Hand Scroll Controller.app"

if [ -d "$APP_SRC" ]; then
    # Remove old copy on Desktop if present
    if [ -d "$DEST" ]; then
        rm -rf "$DEST"
    fi
    cp -r "$APP_SRC" "$DEST"

    echo ""
    echo "================================================"
    echo "  Done!"
    echo ""
    echo "  Hand Scroll Controller.app is on your Desktop."
    echo ""
    echo "  Drag it to your Applications folder, then"
    echo "  double-click it to launch — no Terminal needed."
    echo "================================================"
    echo ""

    osascript -e 'display notification "Hand Scroll Controller.app is ready on your Desktop!" with title "Build Complete" sound name "Glass"'

    # Open Desktop in Finder so the user can see the new app
    open "$DESKTOP"
else
    echo ""
    echo "ERROR: Build failed. Check the output above for details."
    exit 1
fi
