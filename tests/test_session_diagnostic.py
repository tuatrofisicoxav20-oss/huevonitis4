"""El diagnóstico de arranque sólo mira perfiles registrados, no backups sueltos.

Regresión: las carpetas de backup (`default_backup_*`, `default_CORRUPTO_*`) con
manifests que apuntan a PNGs viejos disparaban el modal de diagnóstico al
arrancar aunque el perfil activo estuviera sano → "la app ya no abre".
"""
import json

import pytest


@pytest.fixture
def tipografia(tmp_path, monkeypatch):
    import config
    base = tmp_path / "tipografia_test"
    base.mkdir()
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", base)
    monkeypatch.setattr(config, "PROFILES_FILE", base / "_profiles.json")
    return base


def _write_profile(base, pid, entries):
    d = base / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "_manifest.json").write_text(json.dumps(entries, ensure_ascii=False))
    return d


def test_backups_no_gatillan_missing_pngs(tipografia):
    from core.session_diagnostic import SessionDiagnostic

    # Perfil activo sano: su PNG existe
    d = _write_profile(tipografia, "default", [])
    png = d / "a_000.png"
    png.write_bytes(b"\x89PNG\r\n")
    (d / "_manifest.json").write_text(json.dumps([
        {"char": "a", "image_path": str(png)},
    ], ensure_ascii=False))

    # Backups con PNGs faltantes (no registrados en _profiles.json)
    _write_profile(tipografia, "default_backup_pre_reextract", [
        {"char": "g", "image_path": str(tipografia / "default" / "g_000.png")},
    ])
    _write_profile(tipografia, "default_CORRUPTO_20260530", [
        {"char": "b", "image_path": str(tipografia / "default" / "b_001.png")},
    ])

    (tipografia / "_profiles.json").write_text(json.dumps([
        {"id": "default", "name": "Perfil principal"},
    ], ensure_ascii=False))

    sd = SessionDiagnostic()
    res = {r.name: r for r in sd.run_all()}
    # Sólo el perfil 'default' se escanea → no hay PNGs faltantes
    assert res["missing_pngs"].severity == "ok", res["missing_pngs"].message
    # Y sólo itera el perfil registrado
    dirs = {p.name for p in SessionDiagnostic._iter_profile_dirs()}
    assert dirs == {"default"}


def test_sin_profiles_json_escanea_todo(tipografia):
    """Instalación fresca (sin _profiles.json): no se filtra, se escanea todo."""
    from core.session_diagnostic import SessionDiagnostic
    _write_profile(tipografia, "default", [])
    _write_profile(tipografia, "otro", [])
    dirs = {p.name for p in SessionDiagnostic._iter_profile_dirs()}
    assert dirs == {"default", "otro"}
