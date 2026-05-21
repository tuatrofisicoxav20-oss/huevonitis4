"""Shared fixtures for Huevonitis 4 test suite."""
import os
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
    config.ensure_dirs()
