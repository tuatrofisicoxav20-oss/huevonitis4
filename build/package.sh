#!/usr/bin/env bash
# ============================================================
#  Empaqueta Huevonitis 4 con PyInstaller → dist/huevonitis4/
#  Uso: bash build/package.sh [--onefile]
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ONEFILE=false
[[ "${1:-}" == "--onefile" ]] && ONEFILE=true

echo "[1/4] Generando ícono..."
python3 build/create_icon.py

echo "[2/4] Verificando PyInstaller..."
pip show pyinstaller >/dev/null 2>&1 || pip install pyinstaller

echo "[3/4] Construyendo con PyInstaller..."
if $ONEFILE; then
    pyinstaller main.py \
        --onefile \
        --name huevonitis4 \
        --icon assets/icon.ico \
        --collect-all customtkinter \
        --collect-all PIL \
        --hidden-import cv2 \
        --hidden-import numpy \
        --hidden-import pytesseract \
        --hidden-import docx \
        --hidden-import reportlab \
        --hidden-import tkinter \
        --hidden-import _tkinter \
        --exclude-module matplotlib \
        --exclude-module scipy \
        --exclude-module pandas \
        --distpath dist \
        --workpath build/work \
        --noconsole \
        --noconfirm
    EXEC="dist/huevonitis4"
else
    pyinstaller build/huevonitis4.spec \
        --distpath dist \
        --workpath build/work \
        --noconfirm
    EXEC="dist/huevonitis4/huevonitis4"
fi

echo "[4/4] Creando entrada .desktop para la versión empaquetada..."
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
cp assets/icon.png "$ICON_DIR/huevonitis4.png" 2>/dev/null || true

EXEC_FULL="$ROOT/$EXEC"
cat > "$DESKTOP_DIR/huevonitis4-pkg.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Huevonitis 4 (Bundle)
Comment=Versión empaquetada de Huevonitis 4
Exec=$EXEC_FULL
Icon=huevonitis4
Terminal=false
Categories=Education;Office;
EOF

command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo ""
echo "✓ Build listo: $EXEC_FULL"
echo "  Para lanzar: ./$EXEC"
