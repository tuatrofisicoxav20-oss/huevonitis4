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
# v4.2: el banco se divide por perfil de letra. Default mantiene compat
# con bancos pre-v4.2 que se migran automáticamente a "default/".
PROFILES_FILE = TIPOGRAFIA_DIR / "_profiles.json"
DEFAULT_PROFILE_ID = "default"
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

# Fase 2 — fusión multi-detector. Cuando hay más de un detector (classic_cv +
# alguno neuronal), esta estrategia decide cómo se combinan sus cajas:
#   "union"        — junta todas las cajas (puede duplicar cada letra).
#   "intersection" — sólo cajas con consenso entre detectores.
#   "cascade"      — Y-aware: las cajas neuronales definen la región de texto y
#                    classic_cv aporta los cortes finos de carácter dentro.
# cascade suele ganar al combinar neuronal (cajas de palabra) con classic_cv
# (cajas de carácter). Configurable y medible con run_eval (Fase 4).
GLYPH_DETECTOR_FUSION = "cascade"
# Detectores neuronales a fusionar con classic_cv cuando estén instalados
# (p. ej. ["easyocr"]). Los no disponibles se omiten con un log. Vacío = sólo
# classic_cv (default conservador hasta que la medición confirme que suman).
GLYPH_DETECTORS_EXTRA: list[str] = []
_VALID_FUSION = ("union", "intersection", "cascade")

# Fase 3 — modelo de TrOCR para etiquetar letra manuscrita. Configurable según
# RAM/CPU: small (~170 MB, para CPU lento), base (~400 MB, recomendado), large
# (~1.3 GB, máxima calidad). Se descarga la 1ª vez y queda cacheado en disco.
TROCR_MODEL = "microsoft/trocr-base-handwritten"
_VALID_TROCR_MODELS = (
    "microsoft/trocr-small-handwritten",
    "microsoft/trocr-base-handwritten",
    "microsoft/trocr-large-handwritten",
)

# Alineación asistida por el CNN clasificador de caracteres (juez de cortes).
# Mejora la separación de letras ligadas en fotos de abecedario y marca las
# confusiones como Bronze. Requiere el modelo (core/inkcore/ai/models/) y torch;
# si faltan, degrada solo al pipeline clásico. Se puede forzar con H4_CNN_ALIGN=1.
USE_CNN_ALIGN = True

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
    global GLYPH_DETECTOR_FUSION, GLYPH_DETECTORS_EXTRA, TROCR_MODEL
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
    # Fase 2 — fusión multi-detector. Valores inválidos caen al default sin romper.
    val = s.get("glyph_detector_fusion", "")
    if isinstance(val, str) and val in _VALID_FUSION:
        GLYPH_DETECTOR_FUSION = val
    val = s.get("glyph_detectors_extra")
    if isinstance(val, list):
        GLYPH_DETECTORS_EXTRA = [x for x in val if isinstance(x, str) and x]
    val = s.get("trocr_model", "")
    if isinstance(val, str) and val in _VALID_TROCR_MODELS:
        TROCR_MODEL = val
    with contextlib.suppress(KeyError, ValueError, TypeError):
        v = float(s["min_glyph_quality"])
        if 0.0 <= v <= 1.0:
            MIN_GLYPH_QUALITY = v


def update_settings(updates: dict) -> None:
    """Lee settings.json, aplica `updates` y reescribe ATÓMICAMENTE (tmp+rename).

    Punto único para que la UI persista preferencias (tema, animaciones, perfil
    activo) sin truncar el archivo: antes varios sitios hacían write_text/json.dump
    in-place y un crash a mitad corrompía settings.json (se perdían tema/perfil/
    animaciones). Es read-modify-write del dict completo: pensado para llamarse
    desde el hilo de UI (serializado), no concurrentemente.
    """
    import tempfile
    data: dict = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data.update(updates)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SETTINGS_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
