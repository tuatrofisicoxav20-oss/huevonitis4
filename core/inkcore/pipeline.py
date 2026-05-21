import logging
import shutil
import threading
import time
from pathlib import Path

import config
from core.inkcore.bank import GlyphBank
from core.inkcore.extractor import GlyphExtractor, ExtractionOptions
from core.inkcore.renderer import HandwritingRenderer, RenderOptions
from core.models import GlyphEntry
from core.diagnostics import diagnostics

logger = logging.getLogger(__name__)


def _cleanup_temp_dir() -> None:
    """Remove all PNGs from the temporary extraction directory.

    Called after glyphs have been copied into the permanent bank (or when
    extraction is discarded) so that _temp_extract/ does not accumulate
    gigabytes of orphaned files across sessions.
    """
    temp_dir = config.TIPOGRAFIA_DIR / "_temp_extract"
    if not temp_dir.exists():
        return
    removed = 0
    for png in temp_dir.glob("*.png"):
        try:
            png.unlink()
            removed += 1
        except OSError as e:
            logger.warning(f"Could not remove temp glyph {png}: {e}")
    if removed:
        logger.debug(f"Cleaned up {removed} temp glyph(s) from {temp_dir}")


class InkCorePipeline:
    def __init__(self):
        # Issue #8: track initialisation state so callers can check _ready
        # instead of silently operating on a half-broken service.
        self._ready = False
        try:
            self.bank = GlyphBank()
            self.extractor = GlyphExtractor()
            self.renderer = HandwritingRenderer(self.bank)
            # Lock guards concurrent access to the bank from the extraction
            # thread and the main thread (e.g. save_glyphs_to_bank called
            # while a background extraction is finishing).
            self._bank_lock = threading.Lock()
            self._ready = True
        except Exception as exc:
            logger.error("InkCorePipeline failed to initialise: %s", exc, exc_info=True)
            raise

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

    def save_glyphs_to_bank(self, glyphs: list[GlyphEntry]) -> int:
        saved = 0
        with self._bank_lock:
            for g in glyphs:
                try:
                    result = self.bank.add_glyph(g.char, g.image_path)
                    if result is not None:
                        saved += 1
                except Exception as exc:
                    # Bug fix #5: log instead of silently swallowing so
                    # problematic glyphs are visible in the log.
                    logger.warning(
                        "Failed to add glyph '%s' (%s) to bank: %s",
                        g.char, g.image_path, exc,
                    )
        # reload_bank acquires the lock internally; call outside the block
        self.reload_bank()
        # Bug fix #12: purge temp PNGs now that they have been copied into
        # the permanent bank (or skipped as duplicates). Without this, each
        # extraction session leaves files in _temp_extract/ forever.
        _cleanup_temp_dir()
        return saved

    def discard_extracted_glyphs(self) -> None:
        """Call when the user cancels an extraction without saving to bank.

        Ensures _temp_extract/ is still cleaned up so files don't accumulate.
        """
        _cleanup_temp_dir()

    def render(self, text: str, options: RenderOptions):
        return self.renderer.render_text(text, options)

    def bank_coverage(self) -> dict:
        return self.bank.coverage()
