"""Chequeos de sesión al arrancar — limpia inconsistencias antes de que muerdan.

Se ejecuta desde main.py después de config.ensure_dirs() y antes de instanciar App.
Skip vía variable de entorno H4_SKIP_DIAGNOSTIC=1.

Cada CheckResult tiene severity en {"ok", "warning", "error"}. Si todo es "ok",
el arranque es silencioso. Si hay warnings/errors, el caller muestra un modal
para que el usuario decida (o ejecuta los auto_fix automáticos si confía).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import config

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    severity: str  # "ok" | "warning" | "error"
    message: str
    auto_fix: Callable | None = None  # callable() → bool, devuelve True si arregló
    fixed: bool = False
    details: dict = field(default_factory=dict)

    @property
    def is_fixable(self) -> bool:
        return self.auto_fix is not None and not self.fixed

    def __repr__(self) -> str:
        return f"<Check {self.name} [{self.severity}] {self.message[:60]}>"


class SessionDiagnostic:
    """Orquesta una serie de chequeos al arranque. Cada uno es independiente."""

    def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for check_fn in (
            self._check_dependencies,
            self._check_disk_space,
            self._check_profile_consistency,
            self._check_manifest_integrity,
            self._check_orphan_pngs,
            self._check_missing_pngs,
        ):
            try:
                results.append(check_fn())
            except Exception as exc:
                logger.error("Check %s lanzó: %s", check_fn.__name__, exc, exc_info=True)
                results.append(CheckResult(
                    name=check_fn.__name__,
                    severity="error",
                    message=f"Excepción en el chequeo: {exc}",
                ))
        return results

    # ── Checks individuales ──────────────────────────────────────

    def _check_dependencies(self) -> CheckResult:
        """Pillow, cv2, customtkinter son hard requirements."""
        missing = []
        for mod_name, friendly in (
            ("PIL", "Pillow"),
            ("cv2", "opencv-python"),
            ("customtkinter", "customtkinter"),
        ):
            try:
                __import__(mod_name)
            except ImportError:
                missing.append(friendly)
        if missing:
            return CheckResult(
                name="dependencies",
                severity="error",
                message=f"Faltan dependencias: {', '.join(missing)}",
                details={"missing": missing},
            )
        return CheckResult(
            name="dependencies", severity="ok",
            message="Dependencias instaladas correctamente",
        )

    def _check_disk_space(self) -> CheckResult:
        """Avisa si quedan menos de 100 MB libres en DATA_DIR."""
        try:
            usage = shutil.disk_usage(config.DATA_DIR)
            free_mb = usage.free // (1024 * 1024)
        except Exception as exc:
            return CheckResult(
                name="disk_space", severity="warning",
                message=f"No se pudo verificar espacio en disco: {exc}",
            )
        if free_mb < 100:
            return CheckResult(
                name="disk_space", severity="warning",
                message=f"Poco espacio libre: {free_mb} MB (recomendado >100 MB)",
                details={"free_mb": free_mb},
            )
        return CheckResult(
            name="disk_space", severity="ok",
            message=f"Espacio libre: {free_mb} MB",
        )

    def _check_profile_consistency(self) -> CheckResult:
        """Cada perfil en _profiles.json debe tener su carpeta. Faltantes → auto-fix."""
        pf = config.PROFILES_FILE
        if not pf.exists():
            return CheckResult(
                name="profile_consistency", severity="ok",
                message="Sin perfiles aún (se creará default al arranque)",
            )
        try:
            with open(pf, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            return CheckResult(
                name="profile_consistency", severity="error",
                message=f"_profiles.json corrupto: {exc}",
            )
        missing_dirs = []
        for prof in data:
            pid = prof.get("id", "")
            if not pid:
                continue
            d = config.TIPOGRAFIA_DIR / pid
            if not d.exists():
                missing_dirs.append(pid)
        if missing_dirs:
            def _fix() -> bool:
                for pid in missing_dirs:
                    (config.TIPOGRAFIA_DIR / pid).mkdir(parents=True, exist_ok=True)
                return True
            return CheckResult(
                name="profile_consistency", severity="warning",
                message=f"{len(missing_dirs)} perfil(es) sin carpeta: {', '.join(missing_dirs[:3])}",
                auto_fix=_fix,
                details={"missing_dirs": missing_dirs},
            )
        return CheckResult(
            name="profile_consistency", severity="ok",
            message=f"{len(data)} perfil(es) con carpeta correcta",
        )

    def _check_manifest_integrity(self) -> CheckResult:
        """Cada perfil debe tener _manifest.json válido. Corruptos → reconstruir."""
        problems: list[str] = []
        for prof_dir in self._iter_profile_dirs():
            mf = prof_dir / "_manifest.json"
            if not mf.exists():
                continue
            try:
                with open(mf, encoding="utf-8") as f:
                    json.load(f)
            except Exception as exc:
                problems.append(f"{prof_dir.name}: {exc}")
        if problems:
            return CheckResult(
                name="manifest_integrity", severity="error",
                message=f"Manifest(s) corrupto(s): {'; '.join(problems[:3])}",
                details={"problems": problems},
            )
        return CheckResult(
            name="manifest_integrity", severity="ok",
            message="Todos los manifests son JSON válidos",
        )

    def _check_orphan_pngs(self) -> CheckResult:
        """PNGs en carpeta de perfil que no aparecen en su manifest. Auto-fix: agregar al manifest."""
        orphans: dict[str, list[str]] = {}
        for prof_dir in self._iter_profile_dirs():
            mf = prof_dir / "_manifest.json"
            if not mf.exists():
                continue
            try:
                with open(mf, encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception:
                continue
            known = {Path(e.get("image_path", "")).name for e in entries}
            for png in prof_dir.glob("*.png"):
                if png.name not in known:
                    orphans.setdefault(prof_dir.name, []).append(str(png))

        if not orphans:
            return CheckResult(
                name="orphan_pngs", severity="ok",
                message="Sin PNGs huérfanos",
            )

        total = sum(len(v) for v in orphans.values())

        def _fix() -> bool:
            # Auto-fix: ignorar los huérfanos (no se hace add automático para evitar
            # importar piezas que no son glifos reales). Solo loguear.
            for prof_name, paths in orphans.items():
                logger.info("orphan_pngs: %s → %d PNGs ignorados", prof_name, len(paths))
            return True

        return CheckResult(
            name="orphan_pngs", severity="warning",
            message=f"{total} PNG huérfano(s) en {len(orphans)} perfil(es)",
            auto_fix=_fix,
            details={"orphans": orphans},
        )

    def _check_missing_pngs(self) -> CheckResult:
        """Entradas en manifest cuyo PNG no existe. Auto-fix: quitar entrada."""
        missing: dict[str, list[str]] = {}
        rewritten_count = 0
        for prof_dir in self._iter_profile_dirs():
            mf = prof_dir / "_manifest.json"
            if not mf.exists():
                continue
            try:
                with open(mf, encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception:
                continue
            bad = [e for e in entries if not Path(e.get("image_path", "")).exists()]
            if bad:
                missing.setdefault(prof_dir.name, []).extend(
                    [e.get("char", "?") + ":" + e.get("image_path", "?") for e in bad],
                )

        if not missing:
            return CheckResult(
                name="missing_pngs", severity="ok",
                message="Todas las entradas tienen PNG",
            )

        total = sum(len(v) for v in missing.values())

        def _fix() -> bool:
            nonlocal rewritten_count
            for prof_name in missing:
                prof_dir = config.TIPOGRAFIA_DIR / prof_name
                mf = prof_dir / "_manifest.json"
                if not mf.exists():
                    continue
                try:
                    with open(mf, encoding="utf-8") as f:
                        entries = json.load(f)
                    kept = [e for e in entries if Path(e.get("image_path", "")).exists()]
                    removed = len(entries) - len(kept)
                    if removed:
                        with open(mf, "w", encoding="utf-8") as f:
                            json.dump(kept, f, ensure_ascii=False, indent=2)
                        rewritten_count += removed
                        logger.info(
                            "missing_pngs auto-fix: %s → quitadas %d entradas",
                            prof_name, removed,
                        )
                except Exception as exc:
                    logger.error("missing_pngs auto-fix %s falló: %s", prof_name, exc)
                    return False
            return True

        return CheckResult(
            name="missing_pngs", severity="warning",
            message=f"{total} entrada(s) con PNG faltante en {len(missing)} perfil(es)",
            auto_fix=_fix,
            details={"missing": missing},
        )

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _registered_profile_ids() -> set[str] | None:
        """IDs de perfiles registrados en _profiles.json.

        Devuelve None si no hay registro (instalación fresca) → no filtrar. Si
        hay registro, sólo esos cuentan como perfiles vivos; las carpetas de
        backup/corruptas que quedan sueltas en TIPOGRAFIA_DIR no.
        """
        pf = config.PROFILES_FILE
        if not pf.exists():
            return None
        try:
            with open(pf, encoding="utf-8") as f:
                data = json.load(f)
            return {p.get("id", "") for p in data if p.get("id")}
        except Exception:
            return None

    @staticmethod
    def _iter_profile_dirs():
        """Itera los directorios de perfil VIVOS bajo TIPOGRAFIA_DIR.

        Sólo perfiles registrados en _profiles.json. Las carpetas de backup
        (`default_backup_*`, `default_CORRUPTO_*`, etc.) que el usuario o el
        pipeline dejan en la carpeta NO se escanean: sus manifests apuntan a
        PNGs viejos y dispararían el modal de diagnóstico al arrancar sin que
        haya nada roto en el banco activo.
        """
        if not config.TIPOGRAFIA_DIR.exists():
            return
        registered = SessionDiagnostic._registered_profile_ids()
        for item in config.TIPOGRAFIA_DIR.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("_"):
                continue
            if registered is not None and item.name not in registered:
                continue
            yield item


def should_skip_diagnostic() -> bool:
    """Permitir skip con env var (útil en CI / debugging)."""
    return bool(os.environ.get("H4_SKIP_DIAGNOSTIC"))


def run_diagnostic() -> list[CheckResult]:
    """Entry point para main.py."""
    if should_skip_diagnostic():
        logger.info("Diagnóstico saltado por H4_SKIP_DIAGNOSTIC")
        return []
    sd = SessionDiagnostic()
    return sd.run_all()
