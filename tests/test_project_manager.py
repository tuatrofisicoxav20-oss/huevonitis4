"""Tests for ProjectManager: save/load/autosave/delete + .bak fallback."""

import pytest

from core.models import Project


@pytest.fixture
def pm():
    from core.project_manager import ProjectManager
    return ProjectManager()


def test_save_and_load(pm):
    proj = Project(name="Mi Proyecto")
    pm.save(proj)
    loaded = pm.load(proj.id)
    assert loaded is not None
    assert loaded.name == "Mi Proyecto"
    assert loaded.id == proj.id


def test_load_nonexistent(pm):
    result = pm.load("nonexistent-id")
    assert result is None


def test_list_projects(pm):
    p1 = Project(name="Alpha")
    p2 = Project(name="Beta")
    pm.save(p1)
    pm.save(p2)
    projects = pm.list_projects()
    names = [p.name for p in projects]
    assert "Alpha" in names
    assert "Beta" in names


def test_delete(pm):
    proj = Project(name="Para borrar")
    pm.save(proj)
    pm.delete(proj.id)
    assert pm.load(proj.id) is None


def test_autosave_creates_file(pm):
    import config
    proj = Project(name="Autosave test")
    pm.autosave(proj)
    autosave_file = config.AUTOSAVE_DIR / f"{proj.id}_autosave.json"
    assert autosave_file.exists()


def test_load_with_bak_fallback(pm, tmp_path):
    """If .json is corrupted, load() should fall back to .bak."""
    import config
    proj = Project(name="Backup test")
    pm.save(proj)                    # first save — no .bak yet
    pm.save(proj)                    # second save — creates .bak from first
    proj_path = config.PROJECTS_DIR / f"{proj.id}.json"
    bak_path = proj_path.with_suffix(".bak")
    assert bak_path.exists()
    # Corrupt the main file
    proj_path.write_text("{{invalid json}}")
    loaded = pm.load(proj.id)
    assert loaded is not None
    assert loaded.name == "Backup test"


def test_project_status_saved(pm):
    proj = Project(name="Status test", status="Entregado")
    pm.save(proj)
    loaded = pm.load(proj.id)
    assert loaded.status == "Entregado"
