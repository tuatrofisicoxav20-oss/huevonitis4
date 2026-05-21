#!/usr/bin/env bash
# Desinstalador de Huevonitis 4
set -euo pipefail

APP_ID="huevonitis4"
INSTALL_DIR="$HOME/.local/share/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

echo "Desinstalando Huevonitis 4..."

rm -f "$BIN_DIR/$APP_ID"
rm -f "$DESKTOP_DIR/$APP_ID.desktop"
rm -f "$ICON_DIR/$APP_ID.png"

read -rp "¿Eliminar también los datos de la app (proyectos, banco tipográfico, trabajos)? [s/N] " resp
if [[ "$resp" =~ ^[ssSyY]$ ]]; then
    rm -rf "$INSTALL_DIR"
    echo "Datos eliminados."
else
    # Solo eliminar la app, conservar datos de usuario
    rm -rf "$INSTALL_DIR/app" "$INSTALL_DIR/env"
    echo "Datos de usuario conservados en $INSTALL_DIR"
fi

command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Huevonitis 4 desinstalado."
