"""Gestión de perfiles de letra (v4.2).

Cada perfil agrupa los glifos de una persona en su propia carpeta bajo
TIPOGRAFIA_DIR/{id}/. El índice de perfiles vive en TIPOGRAFIA_DIR/_profiles.json.

Operaciones CRUD: list/create/rename/delete + helpers de migración legacy.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import config
from core.models import HandwritingProfile

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Convierte un display name a un slug filesystem-safe."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "perfil"


class ProfileManager:
    """CRUD de HandwritingProfile + path resolver por id."""

    def __init__(self) -> None:
        self._profiles: list[HandwritingProfile] = []
        self.load()

    # ── IO ────────────────────────────────────────────────────────

    def _profiles_file(self) -> Path:
        return config.PROFILES_FILE

    def _profile_dir(self, profile_id: str) -> Path:
        return config.TIPOGRAFIA_DIR / profile_id

    def load(self) -> None:
        config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
        pf = self._profiles_file()
        if not pf.exists():
            # No hay archivo de perfiles — el caller debe llamar migrate_if_needed
            # o ensure_default_profile.
            self._profiles = []
            return
        try:
            with open(pf, encoding="utf-8") as f:
                data = json.load(f)
            self._profiles = [HandwritingProfile(**d) for d in data]
            logger.info("ProfileManager.load: %d perfiles", len(self._profiles))
        except json.JSONDecodeError as e:
            logger.error("ProfileManager.load: JSON corrupto en %s: %s", pf, e)
            self._profiles = []
        except Exception as e:
            logger.error("ProfileManager.load: %s", e, exc_info=True)
            self._profiles = []

    def _atomic_write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def save(self) -> None:
        self._atomic_write(
            self._profiles_file(),
            [p.__dict__.copy() for p in self._profiles],
        )

    # ── Queries ───────────────────────────────────────────────────

    def list_profiles(self) -> list[HandwritingProfile]:
        return list(self._profiles)

    def get(self, profile_id: str) -> HandwritingProfile | None:
        return next((p for p in self._profiles if p.id == profile_id), None)

    def exists(self, profile_id: str) -> bool:
        return self.get(profile_id) is not None

    def directory_for(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id)

    # ── Mutations ─────────────────────────────────────────────────

    def ensure_default_profile(self) -> None:
        """Si no hay perfiles, crea 'default' y su directorio."""
        if self._profiles:
            return
        default = HandwritingProfile(
            id=config.DEFAULT_PROFILE_ID,
            name="Perfil principal",
            created_at=datetime.now().isoformat(),
            notes="Perfil por defecto.",
        )
        self._profiles.append(default)
        self._profile_dir(default.id).mkdir(parents=True, exist_ok=True)
        self.save()
        logger.info("ensure_default_profile: creado %r", default.id)

    def create_profile(self, name: str, notes: str = "") -> HandwritingProfile:
        """Crea un nuevo perfil con id derivado del nombre. Lanza si ya existe."""
        slug = _slugify(name)
        if self.exists(slug):
            # Agregar sufijo numérico si colisiona
            n = 2
            while self.exists(f"{slug}_{n}"):
                n += 1
            slug = f"{slug}_{n}"
        prof = HandwritingProfile(
            id=slug,
            name=name.strip() or slug,
            created_at=datetime.now().isoformat(),
            notes=notes,
        )
        self._profile_dir(slug).mkdir(parents=True, exist_ok=True)
        self._profiles.append(prof)
        self.save()
        logger.info("create_profile: %r (slug=%r)", name, slug)
        return prof

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        """Cambia el display name del perfil. No cambia el id (path estable)."""
        prof = self.get(profile_id)
        if prof is None:
            return False
        prof.name = new_name.strip() or prof.name
        self.save()
        return True

    def delete_profile(self, profile_id: str, *, delete_data: bool = False) -> bool:
        """Elimina un perfil del índice. Si delete_data=True borra también la carpeta.

        Por seguridad delete_data defaultea False — la carpeta queda en disco
        para que el usuario pueda recuperarla manualmente si fue un error.
        """
        prof = self.get(profile_id)
        if prof is None:
            return False
        if delete_data:
            d = self._profile_dir(profile_id)
            if d.exists():
                try:
                    shutil.rmtree(d)
                    logger.info("delete_profile: borrado dir %s", d)
                except OSError as e:
                    logger.warning("delete_profile: no se pudo borrar %s: %s", d, e)
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        self.save()
        logger.info("delete_profile: %r removido del índice", profile_id)
        return True


# ── Migración legacy ──────────────────────────────────────────────


def needs_legacy_migration() -> bool:
    """True si hay un banco pre-v4.2 que aún no se migró a la estructura de perfiles.

    Heurística robusta: existe TIPOGRAFIA_DIR/_manifest.json en la raíz (no en
    una subcarpeta). Esto detecta legacy aunque _profiles.json ya exista (caso
    edge: pipeline corrió antes que la migración).
    """
    legacy_manifest = config.TIPOGRAFIA_DIR / "_manifest.json"
    return legacy_manifest.exists()


def migrate_legacy_to_default(*, backup: bool = True) -> dict:
    """Mueve el banco legacy plano a tipografia/default/ creando _profiles.json.

    Pasos atómicos:
      1) (opcional) Backup completo de tipografia/ a DATA_DIR/_backup_pre_profiles/
      2) Crear tipografia/default/
      3) Mover *.png de tipografia/ → tipografia/default/ (excepto subdirectorios)
      4) Mover _manifest.json / _manifest.bak a tipografia/default/
      5) Reescribir image_path en el manifest para que apunte a la nueva ubicación
      6) Crear tipografia/_profiles.json con un único perfil "default"

    Devuelve un dict con stats. Lanza si algo falla — caller debe avisar al user
    y NO borrar el backup en ese caso.
    """
    result = {
        "backup_path": None,
        "pngs_moved": 0,
        "manifest_moved": False,
        "manifest_paths_rewritten": 0,
        "profiles_file_created": False,
    }
    tipo = config.TIPOGRAFIA_DIR
    if not needs_legacy_migration():
        logger.info("migrate_legacy_to_default: no se requiere migración")
        return result

    legacy_manifest = tipo / "_manifest.json"
    legacy_bak = tipo / "_manifest.bak"
    default_dir = tipo / config.DEFAULT_PROFILE_ID
    profiles_file = config.PROFILES_FILE

    # 1) Backup
    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = config.DATA_DIR / "_backup_pre_profiles" / f"tipografia_{ts}"
        backup_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Copia, no movimiento — el original sigue intacto hasta el final.
            shutil.copytree(tipo, backup_root, dirs_exist_ok=False)
            result["backup_path"] = str(backup_root)
            logger.info("migrate: backup creado en %s", backup_root)
        except Exception as exc:
            logger.error("migrate: backup falló: %s", exc, exc_info=True)
            raise RuntimeError(f"No se pudo crear backup en {backup_root}: {exc}") from exc

    # 2) Crear default/
    default_dir.mkdir(parents=True, exist_ok=True)

    # 3) Mover PNGs sueltos de la raíz a default/
    moved = 0
    for png in tipo.glob("*.png"):
        if png.is_file():
            try:
                shutil.move(str(png), str(default_dir / png.name))
                moved += 1
            except OSError as exc:
                logger.error("migrate: no se pudo mover %s: %s", png, exc)
                raise
    result["pngs_moved"] = moved
    logger.info("migrate: movidos %d PNGs a %s", moved, default_dir)

    # 4) Mover manifest y bak
    if legacy_manifest.exists():
        try:
            shutil.move(str(legacy_manifest), str(default_dir / "_manifest.json"))
            result["manifest_moved"] = True
        except OSError as exc:
            logger.error("migrate: no se pudo mover manifest: %s", exc)
            raise
    if legacy_bak.exists():
        with contextlib.suppress(OSError):
            shutil.move(str(legacy_bak), str(default_dir / "_manifest.bak"))

    # 5) Reescribir image_path dentro del manifest
    new_manifest = default_dir / "_manifest.json"
    if new_manifest.exists():
        try:
            with open(new_manifest, encoding="utf-8") as f:
                data = json.load(f)
            str(tipo.resolve())
            str(default_dir.resolve())
            rewritten = 0
            for entry in data:
                old_path = entry.get("image_path", "")
                if not old_path:
                    continue
                # Reescribir el path solo si apuntaba al directorio raíz legacy.
                # Acepta el path con o sin resolve (puede tener symlinks).
                op = Path(old_path)
                if op.parent.resolve() == tipo.resolve():
                    entry["image_path"] = str(default_dir / op.name)
                    rewritten += 1
                # Si ya está en default/ o en otra parte, lo dejamos.
                # Asegurar profile_id en cada entry (campo nuevo v4.2)
                entry.setdefault("profile_id", config.DEFAULT_PROFILE_ID)
            with open(new_manifest, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            result["manifest_paths_rewritten"] = rewritten
            logger.info("migrate: reescritas %d rutas en %s", rewritten, new_manifest)
        except Exception as exc:
            logger.error("migrate: error reescribiendo manifest: %s", exc, exc_info=True)
            raise

    # 6) Crear _profiles.json
    pm = ProfileManager()
    pm.ensure_default_profile()
    result["profiles_file_created"] = profiles_file.exists()
    logger.info("migrate: completado %s", result)
    return result
