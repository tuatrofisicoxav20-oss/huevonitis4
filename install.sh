#!/usr/bin/env bash
# ============================================================
#  Huevonitis 4 — Instalador para Linux (Fedora/Ubuntu/Arch)
# ============================================================
set -euo pipefail

APP_NAME="Huevonitis 4"
APP_ID="huevonitis4"
VERSION="4.0.1"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ── 1. Prerequisitos ─────────────────────────────────────────

info "Verificando Python 3..."
python3 --version >/dev/null 2>&1 || error "Python 3 no encontrado. Instalar: sudo dnf install python3"

PY_VER=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_VER" -lt 10 ]; then
    error "Se requiere Python 3.10+. Versión actual: 3.$PY_VER"
fi
success "Python OK"

info "Verificando tkinter..."
python3 -c "import tkinter" 2>/dev/null || {
    warn "tkinter no encontrado. Instalando..."
    if command -v dnf >/dev/null; then
        sudo dnf install -y python3-tkinter
    elif command -v apt >/dev/null; then
        sudo apt install -y python3-tk
    elif command -v pacman >/dev/null; then
        sudo pacman -S --noconfirm tk
    fi
}
success "tkinter OK"

# ── 2. Crear entorno virtual ─────────────────────────────────

info "Creando entorno virtual en $INSTALL_DIR/env ..."
mkdir -p "$INSTALL_DIR"
python3 -m venv "$INSTALL_DIR/env"
source "$INSTALL_DIR/env/bin/activate"
pip install --upgrade pip -q

# ── 3. Instalar dependencias ─────────────────────────────────

info "Instalando dependencias Python..."
pip install -q \
    "customtkinter>=5.2.0" \
    "Pillow>=11.0" \
    "opencv-python>=4.10" \
    "pytesseract>=0.3.13" \
    "python-docx>=1.2" \
    "reportlab>=4.4" \
    "numpy>=2.0" \
    "lxml>=6.0" \
    "tqdm>=4.66" \
    "pdf2image>=1.17" \
    "pdfplumber>=0.11"
success "Dependencias instaladas"
deactivate

# ── 4. Copiar archivos de la app ─────────────────────────────

info "Copiando archivos de la aplicación..."
APP_DIR="$INSTALL_DIR/app"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude="__pycache__" --exclude="*.pyc" \
    --exclude=".git" --exclude="build/work" --exclude="dist" \
    "$SRC_DIR/" "$APP_DIR/"
success "Archivos copiados"

# ── 5. Crear script lanzador ─────────────────────────────────

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/$APP_ID"
cat > "$LAUNCHER" << LAUNCHER_EOF
#!/usr/bin/env bash
# Lanzador de Huevonitis 4
export PYTHONDONTWRITEBYTECODE=1
source "$INSTALL_DIR/env/bin/activate"
exec python3 "$APP_DIR/main.py" "\$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER"
success "Lanzador creado en $LAUNCHER"

# ── 6. Instalar ícono ────────────────────────────────────────

mkdir -p "$ICON_DIR"
if [ -f "$APP_DIR/assets/icon.png" ]; then
    cp "$APP_DIR/assets/icon.png" "$ICON_DIR/$APP_ID.png"
    success "Ícono instalado"
else
    warn "Ícono no encontrado, generando..."
    source "$INSTALL_DIR/env/bin/activate"
    python3 "$APP_DIR/build/create_icon.py" 2>/dev/null || true
    deactivate
    [ -f "$APP_DIR/assets/icon.png" ] && cp "$APP_DIR/assets/icon.png" "$ICON_DIR/$APP_ID.png"
fi

# ── 7. Crear entrada .desktop ────────────────────────────────

mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/$APP_ID.desktop" << DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Huevonitis 4
GenericName=Editor de Apuntes
Comment=Produce apuntes con tu letra real y gestiona trabajos escolares
Exec=$LAUNCHER %u
Icon=$APP_ID
Terminal=false
StartupNotify=true
StartupWMClass=huevonitis4
Categories=Education;Office;Utility;
Keywords=apuntes;letra;estudiante;escuela;manuscrito;flashcards;
MimeType=
DESKTOP_EOF

chmod +x "$DESKTOP_DIR/$APP_ID.desktop"
success "Entrada de escritorio creada"

# ── 8. Actualizar bases de datos de escritorio ───────────────

if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# ── 9. Verificar PATH ────────────────────────────────────────

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    warn "Agrega $BIN_DIR a tu PATH:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo "  source ~/.bashrc"
fi

# ── Fin ──────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Huevonitis 4 instalado correctamente   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  Abrir desde terminal:  $APP_ID"
echo "  Abrir desde menú:      Busca 'Huevonitis' en Actividades (GNOME)"
echo "  Desinstalar:           bash $SRC_DIR/uninstall.sh"
echo ""

# Preguntar si lanzar ahora
read -rp "¿Lanzar Huevonitis 4 ahora? [s/N] " resp
if [[ "$resp" =~ ^[ssSyY]$ ]]; then
    "$LAUNCHER" &
    disown
fi
