"""ExtractorTabSaveMixin — guardado de glifos extraídos al banco.

Separado de extractor_tab.py para mantener cada archivo manejable.
Cubre el flujo de "💾 Guardar en banco": pre-chequeo de PNG temporales,
normalización de stats, mensajes al usuario y re-mapeo de rutas temporales
a rutas permanentes del banco.

Depende de:
  • self._extracted, self._pipeline
  • self.toast, self._set_status, self._refresh_bank, self._show_extracted_grid
"""
import logging
from pathlib import Path

from ui import theme

logger = logging.getLogger(__name__)


class ExtractorTabSaveMixin:
    """Guardado al banco + helpers de estado/rutas; mezclado en InkCoreView."""

    def _save_to_bank(self):
        logger.info("_save_to_bank: invocado, %d glifos extraídos", len(self._extracted))
        if not self._extracted:
            self.toast("No hay glifos para guardar", "warning")
            self._set_status("⚠ Sin glifos para guardar — extrae primero", theme.ACCENT_ORANGE)
            logger.warning("_save_to_bank: lista vacía, abortando")
            return
        total = len(self._extracted)
        # Pre-chequeo: glifos cuyo PNG temporal ya no existe se descartarían
        # silenciosamente dentro de bank.add_glyph (devuelve None). Detectarlos
        # antes nos permite avisarle al usuario en vez de mostrar "0 guardados".
        missing = [g for g in self._extracted if not Path(g.image_path).exists()]
        if missing:
            logger.warning(
                "_save_to_bank: %d/%d glifos sin PNG temporal (probable cleanup previo)",
                len(missing), total,
            )
        try:
            stats = self._pipeline.save_glyphs_to_bank(self._extracted)
            logger.info("_save_to_bank: pipeline stats=%s", stats)
        except Exception as exc:
            logger.error("_save_to_bank: pipeline lanzó: %s", exc, exc_info=True)
            self.toast(f"Error al guardar: {exc}", "error")
            self._set_status(f"⚠ Error: {exc}", theme.ACCENT_RED)
            return
        # BUG-11: stats dict en lugar de int. Backward-compat: si por alguna razón
        # vuelve un int (mock o caller legacy), normalizar.
        if isinstance(stats, int):
            stats = {
                "saved": stats, "duplicates": 0,
                "missing_source": len(missing), "errors": 0,
            }
        saved = stats["saved"]
        dupes = stats["duplicates"]
        missing_in_pipe = stats["missing_source"]
        errors = stats["errors"]
        if saved == 0:
            if missing_in_pipe and not dupes:
                msg = f"Nada guardado: {missing_in_pipe} PNG temporales ya no existen (re-extrae)"
                self.toast(msg, "warning")
                self._set_status(f"⚠ {msg}", theme.ACCENT_ORANGE)
            elif dupes == total:
                msg = f"Nada nuevo: los {total} glifos ya estaban en el banco"
                self.toast(msg, "warning")
                self._set_status(f"ℹ {msg}", theme.ACCENT_BLUE)
            elif errors:
                msg = f"Nada guardado — {errors} errores, revisa el log"
                self.toast(msg, "error")
                self._set_status(f"⚠ {msg}", theme.ACCENT_RED)
            else:
                self.toast("Nada guardado — revisa el log", "warning")
                self._set_status("⚠ Nada guardado — revisa el log", theme.ACCENT_ORANGE)
        else:
            msg = f"{saved} glifos guardados"
            extras = []
            if dupes:
                extras.append(f"{dupes} duplicados")
            if missing_in_pipe:
                extras.append(f"{missing_in_pipe} sin archivo")
            if errors:
                extras.append(f"{errors} errores")
            if extras:
                msg += f"  ({', '.join(extras)})"
            kind = "warning" if errors else "success"
            self.toast(msg, kind)
            # Cobertura del banco COMPLETO tras guardar: guía el flujo
            # multi-imagen ("faltan g m n → cargá otra foto con esas").
            bank_cov = ""
            try:
                from core.inkcore.alphabet_coverage import coverage_message
                bank_chars = [e.char for e in self._pipeline.bank.get_all()]
                bank_cov = "\n" + coverage_message(bank_chars, scope="Banco")
            except Exception as exc:
                logger.warning("_save_to_bank: cobertura no disponible: %s", exc)
            self._set_status(
                f"✓ {msg}{bank_cov}",
                theme.ACCENT_GREEN if not errors else theme.ACCENT_ORANGE,
            )
            # save_glyphs_to_bank llama _cleanup_temp_dir() internamente, así
            # que los PNG temporales ya no existen. Reemplazamos las rutas en
            # self._extracted con las entradas permanentes del banco para que
            # un segundo clic en "Guardar en banco" detecte correctamente los
            # glifos como "ya en el banco" (duplicados) en vez de "archivo no existe".
            self._update_extracted_to_bank_paths()
        try:
            self._refresh_bank()
            logger.info("_save_to_bank: banco refrescado OK")
        except Exception as exc:
            logger.error("_save_to_bank: _refresh_bank lanzó: %s", exc, exc_info=True)

    def _set_status(self, text: str, color: str) -> None:
        """Helper: actualiza el label de status de extracción si existe.

        Existe como fallback visible cuando el toast no aparece (HiDPI, manager
        no inicializado, etc.). Falla silenciosamente si el widget aún no se
        creó.
        """
        try:
            self._extract_status.configure(text=text, text_color=color)
        except (AttributeError, Exception):
            pass

    def _update_extracted_to_bank_paths(self) -> None:
        """Reemplaza rutas temporales de self._extracted con rutas permanentes del banco.

        Después de save_glyphs_to_bank + _cleanup_temp_dir los PNGs en _temp_extract
        ya no existen. Busca las entradas correspondientes en el banco (por char,
        índice más reciente) y actualiza self._extracted para que apunten a archivos
        válidos. Evita el bug de "segundo clic falla con archivo no existe".
        """
        bank_all = self._pipeline.bank.get_all()
        bank_by_char: dict[str, list] = {}
        for e in bank_all:
            bank_by_char.setdefault(e.char, []).append(e)

        assigned: set[str] = set()
        new_extracted = []
        for g in self._extracted:
            cands = sorted(
                bank_by_char.get(g.char, []),
                key=lambda e: e.index,
                reverse=True,
            )
            best = next((e for e in cands if e.image_path not in assigned), None)
            if best:
                assigned.add(best.image_path)
                new_extracted.append(best)
        self._extracted = new_extracted
        self._show_extracted_grid()
