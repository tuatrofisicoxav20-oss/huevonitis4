"""Shared fixtures for Huevonitis 4 test suite."""
import sys
from pathlib import Path

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture(autouse=True)
def patch_config_dirs(tmp_path, monkeypatch):
    """Redirect all DATA_DIR paths to a temp directory for each test."""
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipografia")
    monkeypatch.setattr(config, "BUSINESS_DIR", tmp_path / "business")
    monkeypatch.setattr(config, "AUTOSAVE_DIR", tmp_path / "autosave")
    monkeypatch.setattr(config, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    # El juez de cortes por CNN se apaga en tests: son deterministas y rápidos,
    # y no deben depender del modelo entrenado ni de su latencia. Los tests que
    # ejercitan el CNN lo activan explícitamente.
    monkeypatch.setattr(config, "USE_CNN_ALIGN", False, raising=False)
    config.ensure_dirs()
