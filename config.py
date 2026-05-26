import contextlib
import json
import os
from pathlib import Path


def _read_version() -> str:
    """SSOT: el archivo VERSION en la raíz del repo es la fuente única.

    Si por alguna razón no se puede leer (bundle empaquetado raro), caemos
    a un string seguro en vez de romper el arranque.
    """
    try:
        return (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0-unknown"


VERSION = _read_version()
APP_NAME = "Huevonitis 4"

DATA_DIR = Path.home() / ".local" / "share" / "huevonitis4"
PROJECTS_DIR = DATA_DIR / "projects"
TIPOGRAFIA_DIR = DATA_DIR / "tipografia"
BUSINESS_DIR = DATA_DIR / "business"
AUTOSAVE_DIR = DATA_DIR / "autosave"
EXPORTS_DIR = DATA_DIR / "exports"
MODELS_DIR = DATA_DIR / "models"
OCR_CACHE_DIR = DATA_DIR / "ocr_cache"
DEBUG_DIR = DATA_DIR / "debug_extractions"
LOG_FILE = DATA_DIR / "app.log"
SETTINGS_FILE = DATA_DIR / "settings.json"

TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "tesseract")

# Backends intercambiables — default Tesseract (sin dependencias nuevas)
OCR_BACKEND = "tesseract"
GLYPH_DETECTOR = "classic_cv"

MIN_GLYPH_QUALITY = 0.18

BASE_PRICE_PER_PAGE_MXN = 50.0
AUTOSAVE_INTERVAL_MS = 30_000

WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 600
WINDOW_DEFAULT_WIDTH = 1300
WINDOW_DEFAULT_HEIGHT = 860

SIDEBAR_EXPANDED_WIDTH = 220
SIDEBAR_COLLAPSED_WIDTH = 52

def ensure_dirs():
    for d in [PROJECTS_DIR, TIPOGRAFIA_DIR, BUSINESS_DIR, AUTOSAVE_DIR,
              EXPORTS_DIR, MODELS_DIR, OCR_CACHE_DIR, DEBUG_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> None:
    """Override module-level defaults from SETTINGS_FILE if present and valid."""
    global BASE_PRICE_PER_PAGE_MXN, AUTOSAVE_INTERVAL_MS, TESSERACT_CMD
    global OCR_BACKEND, GLYPH_DETECTOR, MIN_GLYPH_QUALITY
    if not SETTINGS_FILE.exists():
        return
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return
    with contextlib.suppress(KeyError, ValueError, TypeError):
        BASE_PRICE_PER_PAGE_MXN = float(s["base_price"])
    with contextlib.suppress(KeyError, ValueError, TypeError):
        v = int(s["autosave_interval"])
        if v > 0:
            AUTOSAVE_INTERVAL_MS = v * 1000
    val = s.get("tesseract_path", "")
    if isinstance(val, str) and val:
        TESSERACT_CMD = val
    val = s.get("ocr_backend", "")
    if isinstance(val, str) and val:
        OCR_BACKEND = val
    val = s.get("glyph_detector", "")
    if isinstance(val, str) and val:
        GLYPH_DETECTOR = val
    with contextlib.suppress(KeyError, ValueError, TypeError):
        v = float(s["min_glyph_quality"])
        if 0.0 <= v <= 1.0:
            MIN_GLYPH_QUALITY = v
