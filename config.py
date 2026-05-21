import os
from pathlib import Path

VERSION = "4.0.0"
APP_NAME = "Huevonitis 4"

DATA_DIR = Path.home() / ".local" / "share" / "huevonitis4"
PROJECTS_DIR = DATA_DIR / "projects"
TIPOGRAFIA_DIR = DATA_DIR / "tipografia"
BUSINESS_DIR = DATA_DIR / "business"
AUTOSAVE_DIR = DATA_DIR / "autosave"
EXPORTS_DIR = DATA_DIR / "exports"
LOG_FILE = DATA_DIR / "app.log"
SETTINGS_FILE = DATA_DIR / "settings.json"

TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "tesseract")

BASE_PRICE_PER_PAGE_MXN = 50.0
AUTOSAVE_INTERVAL_MS = 30_000

WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 600
WINDOW_DEFAULT_WIDTH = 1300
WINDOW_DEFAULT_HEIGHT = 860

SIDEBAR_EXPANDED_WIDTH = 220
SIDEBAR_COLLAPSED_WIDTH = 52

def ensure_dirs():
    for d in [PROJECTS_DIR, TIPOGRAFIA_DIR, BUSINESS_DIR, AUTOSAVE_DIR, EXPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
