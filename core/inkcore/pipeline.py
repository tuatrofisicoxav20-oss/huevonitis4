import logging
import threading
import time
from pathlib import Path

import config
from core.diagnostics import diagnostics
from core.inkcore.bank import GlyphBank
from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
from core.inkcore.renderer import HandwritingRenderer
from core.models import GlyphEntry

logger = logging.getLogger(__name__)


def _cleanup_temp_dir(paths_to_remove: list[str] | None = None) -> None:
    """BUG-02: cleanup SELECTIVO de _temp_extract.

    Si paths_to_remove es None, limpia todo el dir (comportamiento legacy
    usado al descartar una extracción). Si se pasa una lista de paths,
    solo elimina esos específicos.

    Esto evita que el Extractor borre temporales pendientes de aprobación
    del bulk capture al hacer save.
    """
    temp_dir = config.TIPOGRAFIA_DIR / "_temp_extract"
    if not temp_dir.exists():
        return
    if paths_to_remove is None:
        targets = list(temp_dir.glob("*.png"))
    else:
        # Solo aceptar paths que están dentro del temp_dir (evita borrar otros archivos)
        targets = [Path(p) for p in paths_to_remove
                   if Path(p).exists() and Path(p).parent == temp_dir]
    removed = 0
    for png in targets:
        try:
            png.unlink()
            removed += 1
        except OSError as e:
            logger.warning(f"Could not remove temp glyph {png}: {e}")
    if removed:
        logger.debug(f"Cleaned up {removed} temp glyph(s) from {temp_dir}")


class InkCorePipeline:
    def __init__(self, profile_id: str | None = None):
        try:
            from core.inkcore.profile_manager import (
                ProfileManager,
                migrate_legacy_to_default,
                needs_legacy_migration,
            )
            # Defensa en profundidad: si llegamos acá con banco legacy sin migrar
            # (puede pasar al correr desde scripts/tests que no pasan por main.py),
            # migrar ahora. main.py también ejecuta esto al arranque.
            if needs_legacy_migration():
                try:
                    migrate_legacy_to_default(backup=True)
                    logger.info("Pipeline: migración legacy completada en init")
                except Exception as exc:
                    logger.error("Pipeline: migración legacy falló: %s", exc, exc_info=True)
            self.profile_manager = ProfileManager()
            # Asegurar que existe al menos un perfil. Si el usuario tiene un
            # banco legacy (sin _profiles.json) se debió migrar ANTES de llegar
            # acá (main.py lo hace al arranque). Si no, creamos default vacío.
            self.profile_manager.ensure_default_profile()
            self.active_profile_id = profile_id or config.DEFAULT_PROFILE_ID
            if not self.profile_manager.exists(self.active_profile_id):
                logger.warning(
                    "InkCorePipeline: perfil %r no existe, cayendo a default",
                    self.active_profile_id,
                )
                self.active_profile_id = config.DEFAULT_PROFILE_ID
            self.bank = GlyphBank(profile_id=self.active_profile_id)
            self.extractor = GlyphExtractor()
            self.renderer = HandwritingRenderer(self.bank)
            # Lock guards concurrent access to the bank from the extraction
            # thread and the main thread (e.g. save_glyphs_to_bank called
            # while a background extraction is finishing).
            self._bank_lock = threading.Lock()
            # Pre-cargamos TrOCR en background — no bloquea el arranque
            # pero deja el modelo caliente cuando el usuario pulse Procesar.
            # Cold start TrOCR: ~12s → warm: ~2.5s (ganancia ~10s).
            self._preload_thread = threading.Thread(
                target=self._preload_ocr, name="trocr-preload", daemon=True,
            )
            self._preload_thread.start()
        except Exception as exc:
            logger.error("InkCorePipeline failed to initialise: %s", exc, exc_info=True)
            raise

    def switch_profile(self, profile_id: str) -> bool:
        """Cambia el perfil activo. Reinstancia el banco apuntando al nuevo dir.

        Devuelve False si el perfil no existe (no cambia nada en ese caso).
        """
        if not self.profile_manager.exists(profile_id):
            logger.warning("switch_profile: %r no existe en el índice", profile_id)
            return False
        if profile_id == self.active_profile_id:
            return True
        with self._bank_lock:
            try:
                self.active_profile_id = profile_id
                self.bank = GlyphBank(profile_id=profile_id)
                if self.renderer is None:
                    self.renderer = HandwritingRenderer(self.bank)
                else:
                    self.renderer.bank = self.bank
                logger.info("switch_profile: ahora activo %r", profile_id)
                return True
            except Exception as exc:
                logger.error("switch_profile: error: %s", exc, exc_info=True)
                return False

    def list_profiles(self) -> list:
        return self.profile_manager.list_profiles()

    def create_profile(self, name: str, notes: str = ""):
        return self.profile_manager.create_profile(name, notes)

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        return self.profile_manager.rename_profile(profile_id, new_name)

    def delete_profile(self, profile_id: str, *, delete_data: bool = False) -> bool:
        # Si borramos el perfil activo, cambiar a default primero.
        if profile_id == self.active_profile_id:
            default_id = config.DEFAULT_PROFILE_ID
            if profile_id == default_id:
                logger.warning("delete_profile: no se puede borrar el perfil default")
                return False
            self.switch_profile(default_id)
        return self.profile_manager.delete_profile(profile_id, delete_data=delete_data)

    @staticmethod
    def _preload_ocr() -> None:
        try:
            from core.inkcore.auto_text import preload_trocr
            preload_trocr()
        except Exception as exc:
            logger.debug("preload_ocr ignorado: %s", exc)

    def reload_extractor(self) -> None:
        """Reinicializa GlyphExtractor para tomar el nuevo GLYPH_DETECTOR desde config.

        Llamar cuando el usuario cambia el detector de glifos en Configuración.
        Usa el mismo lock que reload_bank() para no colisionar con extracciones en curso.
        """
        with self._bank_lock:
            try:
                self.extractor = GlyphExtractor()
                det = getattr(config, "GLYPH_DETECTOR", "classic_cv")
                logger.info("GlyphExtractor reinicializado (detector: %s)", det)
            except Exception as exc:
                logger.error(
                    "Error al reinicializar GlyphExtractor: %s", exc, exc_info=True
                )

    def reload_bank(self):
        with self._bank_lock:
            t0 = time.perf_counter()
            self.bank.load()
            if self.renderer is None:
                self.renderer = HandwritingRenderer(self.bank)
            else:
                self.renderer.bank = self.bank  # actualiza referencia, preserva cache
            elapsed_ms = (time.perf_counter() - t0) * 1000
            diagnostics.log_timing("reload_bank", elapsed_ms)

    def extract(
        self,
        image_path: str,
        reference_text: str,
        options: ExtractionOptions | None = None,
    ) -> list[GlyphEntry]:
        t0 = time.perf_counter()
        try:
            result = self.extractor.extract_from_image(image_path, reference_text, options)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            diagnostics.log_timing("extract", elapsed_ms)
            diagnostics.log_event("inkcore", "extract_done", f"{len(result)} glifos")
            return result
        except Exception as exc:
            diagnostics.log_error("extract", exc)
            raise

    def save_glyphs_to_bank(self, glyphs: list[GlyphEntry]) -> "dict | int":
        """BUG-11: devuelve dict con stats explícitos: saved/duplicates/missing_source/errors.

        Para compat hacia atrás con callers que esperan int, los stats incluyen
        también el resultado como integer en stats["saved"]. La forma recomendada
        es: ``stats = pipeline.save_glyphs_to_bank(glyphs); n = stats["saved"]``.

        Si algún caller legacy hace ``n = pipeline.save_glyphs_to_bank(glyphs)``
        recibe el dict (que es truthy), no rompe pero pierde precisión.
        """
        logger.info("save_glyphs_to_bank: start, %d glifos a procesar", len(glyphs))
        stats = {"saved": 0, "duplicates": 0, "missing_source": 0, "errors": 0}
        consumed_paths: list[str] = []
        # PERF-01: un solo write al manifest por bulk en vez de N
        self.bank.begin_batch()
        with self._bank_lock:
            for g in glyphs:
                if not Path(g.image_path).exists():
                    stats["missing_source"] += 1
                    logger.info(
                        "save_glyphs_to_bank: ✕ %r src missing: %s",
                        g.char, g.image_path,
                    )
                    continue
                try:
                    has_pipeline_meta = (
                        g.predicted_char is not None
                        or g.label_confidence is not None
                        or bool(g.detector_sources)
                    )
                    quality_override = None
                    if has_pipeline_meta:
                        quality_override = {
                            "score": g.quality_score,
                            "tier": g.tier,
                            "ink_coverage": g.ink_coverage,
                        }
                    result = self.bank.add_glyph(
                        g.char, g.image_path,
                        predicted_char=g.predicted_char,
                        label_confidence=g.label_confidence,
                        detector_sources=g.detector_sources,
                        quality_override=quality_override,
                    )
                    if result is not None:
                        stats["saved"] += 1
                        consumed_paths.append(g.image_path)
                        logger.info(
                            "save_glyphs_to_bank: ✓ %r → %s",
                            g.char, result.image_path,
                        )
                    else:
                        stats["duplicates"] += 1
                        consumed_paths.append(g.image_path)  # también limpiar dupes
                        logger.info(
                            "save_glyphs_to_bank: ⊘ %r duplicado src=%s",
                            g.char, g.image_path,
                        )
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "save_glyphs_to_bank: ✕ glyph %r (%s) falló: %s",
                        g.char, g.image_path, exc, exc_info=True,
                    )
        # PERF-01: flush al manifest una sola vez al cerrar el batch
        self.bank.end_batch()
        logger.info(
            "save_glyphs_to_bank: done saved=%d duplicates=%d missing=%d errors=%d total=%d",
            stats["saved"], stats["duplicates"], stats["missing_source"],
            stats["errors"], len(glyphs),
        )
        self.reload_bank()
        # BUG-02: cleanup SELECTIVO — solo los que se consumieron, no todo el dir.
        # Esto evita borrar candidatos pendientes de bulk capture.
        _cleanup_temp_dir(consumed_paths)
        return stats

    def bank_coverage(self) -> dict:
        return self.bank.coverage()
