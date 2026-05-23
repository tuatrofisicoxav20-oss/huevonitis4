#!/usr/bin/env python3
"""
Huevonitis 4 — Doctor de diagnóstico.

Verifica dependencias, directorios de datos y configuración.
Ejecutar desde la raíz del proyecto:

    python tools/doctor.py
"""
from __future__ import annotations

import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"

_ok = 0
_warn = 0
_err = 0


def ok(msg: str) -> None:
    global _ok
    _ok += 1
    print(f"  {GREEN}✔{RESET}  {msg}")


def warn(msg: str) -> None:
    global _warn
    _warn += 1
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def err(msg: str) -> None:
    global _err
    _err += 1
    print(f"  {RED}✘{RESET}  {msg}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# ── Python version ─────────────────────────────────────────────────────────────

section("Python")
v = sys.version_info
if v >= (3, 10):
    ok(f"Python {v.major}.{v.minor}.{v.micro}")
else:
    err(f"Python {v.major}.{v.minor}.{v.micro} — se requiere 3.10+")

# ── Required dependencies ──────────────────────────────────────────────────────

section("Dependencias requeridas")

REQUIRED = [
    ("customtkinter", "customtkinter"),
    ("PIL", "Pillow"),
    ("cv2", "opencv-python"),
    ("pytesseract", "pytesseract"),
    ("docx", "python-docx"),
    ("reportlab", "reportlab"),
    ("numpy", "numpy"),
    ("lxml", "lxml"),
    ("tqdm", "tqdm"),
]

for mod, pkg in REQUIRED:
    try:
        __import__(mod)
        ok(pkg)
    except ImportError:
        err(f"{pkg}  →  pip install {pkg}")

# ── Optional dependencies ──────────────────────────────────────────────────────

section("Dependencias opcionales (PDF/ML)")

OPTIONAL = [
    ("pdf2image", "pdf2image", "para procesar PDFs escaneados en InkCore"),
    ("pdfplumber", "pdfplumber", "para leer texto de PDFs en Estudio"),
    ("transformers", "transformers", "para TrOCR (etiquetado automático de glifos)"),
    ("torch", "torch", "para TrOCR (etiquetado automático de glifos)"),
    ("easyocr", "easyocr", "backend OCR alternativo"),
    ("psutil", "psutil", "para reportes de uso de RAM en el panel pipeline"),
]

for mod, pkg, reason in OPTIONAL:
    try:
        __import__(mod)
        ok(pkg)
    except ImportError:
        warn(f"{pkg} no instalado — {reason}")

# ── System tools ───────────────────────────────────────────────────────────────

section("Herramientas del sistema")

if shutil.which("tesseract"):
    ok("tesseract en PATH")
else:
    warn("tesseract no encontrado — OCR de imágenes no funcionará\n"
         "     Instalar: sudo dnf install tesseract tesseract-langpack-spa")

if shutil.which("pdftoppm") or shutil.which("gs"):
    ok("poppler/ghostscript disponible para pdf2image")
else:
    warn("poppler no encontrado — pdf2image puede fallar\n"
         "     Instalar: sudo dnf install poppler-utils")

# ── Data directories ───────────────────────────────────────────────────────────

section("Directorios de datos")

import config  # noqa: E402

DIRS = [
    (config.DATA_DIR, "DATA_DIR"),
    (config.PROJECTS_DIR, "PROJECTS_DIR"),
    (config.TIPOGRAFIA_DIR, "TIPOGRAFIA_DIR"),
    (config.BUSINESS_DIR, "BUSINESS_DIR"),
    (config.AUTOSAVE_DIR, "AUTOSAVE_DIR"),
    (config.EXPORTS_DIR, "EXPORTS_DIR"),
    (config.MODELS_DIR, "MODELS_DIR"),
    (config.OCR_CACHE_DIR, "OCR_CACHE_DIR"),
]

for d, name in DIRS:
    if d.exists():
        ok(f"{name}: {d}")
    else:
        warn(f"{name} no existe aún — se creará al iniciar la app\n     ({d})")

# ── Settings file ──────────────────────────────────────────────────────────────

section("Configuración")

if config.SETTINGS_FILE.exists():
    import json
    try:
        with open(config.SETTINGS_FILE) as f:
            s = json.load(f)
        ok(f"settings.json válido ({len(s)} claves)")
    except Exception as exc:
        err(f"settings.json no se puede leer: {exc}")
else:
    warn("settings.json no existe — se usarán valores por defecto")

ok(f"Versión: {config.VERSION}")
ok(f"MIN_GLYPH_QUALITY: {config.MIN_GLYPH_QUALITY}")

# ── GlyphBank ─────────────────────────────────────────────────────────────────

section("Banco de glifos")

try:
    from core.inkcore.bank import GlyphBank
    bank = GlyphBank()
    n = len(bank._entries)
    ok(f"GlyphBank cargado — {n} glifos")
except Exception as exc:
    warn(f"GlyphBank: {exc}")

# ── Summary ────────────────────────────────────────────────────────────────────

print(f"\n{BOLD}{'─'*50}{RESET}")
total = _ok + _warn + _err
print(f"  Total: {total}  |  {GREEN}✔ {_ok}{RESET}  {YELLOW}⚠ {_warn}{RESET}  {RED}✘ {_err}{RESET}")

if _err:
    print(f"\n{RED}Hay errores críticos. Instala las dependencias faltantes antes de usar la app.{RESET}")
    sys.exit(1)
elif _warn:
    print(f"\n{YELLOW}Algunas funciones opcionales no están disponibles.{RESET}")
else:
    print(f"\n{GREEN}Todo OK — Huevonitis 4 está listo para usar.{RESET}")
