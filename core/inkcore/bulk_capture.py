"""
Captura masiva de glifos: procesa múltiples imágenes/PDFs en lote,
devuelve candidatos listos para revisión y aprobación al banco.
"""
from __future__ import annotations

import logging
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from core.models import GlyphEntry

logger = logging.getLogger(__name__)


@dataclass
class BulkGlyphCandidate:
    """Glifo extraído pendiente de aprobación al banco."""
    glyph: GlyphEntry
    source_image: str
    source_page_num: int
    decision: Literal["pending", "approved", "rejected"] = "pending"
    user_label: str = ""

    @property
    def display_char(self) -> str:
        """Char que se guardará. Prioridad: user_label > predicted_char > char."""
        return self.user_label or self.glyph.predicted_char or self.glyph.char or "?"

    @property
    def needs_review(self) -> bool:
        """Glifo de baja confianza — requiere atención manual."""
        lc = self.glyph.label_confidence
        return (lc is None or lc < 0.7) or self.glyph.tier == "Bronze"


@dataclass
class BulkCaptureSession:
    """Sesión activa de captura masiva — efímera, solo en memoria."""
    sources: list[str]
    candidates: list[BulkGlyphCandidate] = field(default_factory=list)
    pipeline_config: object = None

    def stats(self) -> dict:
        return {
            "total": len(self.candidates),
            "pending": sum(1 for c in self.candidates if c.decision == "pending"),
            "approved": sum(1 for c in self.candidates if c.decision == "approved"),
            "rejected": sum(1 for c in self.candidates if c.decision == "rejected"),
            "needs_review": sum(1 for c in self.candidates if c.needs_review),
            "by_char": Counter(c.display_char for c in self.candidates),
        }


def _rasterize_pdf(pdf_path: str, dpi: int = 200) -> list[tuple[str, int]]:
    """Rasteriza PDF a PNGs temporales. Devuelve [(temp_path, page_num)]."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logger.warning("pdf2image no disponible — saltando PDF '%s'", pdf_path)
        return []
    tmp_dir = tempfile.mkdtemp(prefix="bulk_raster_")
    try:
        pages = convert_from_path(
            pdf_path, dpi=dpi, fmt="png",
            output_folder=tmp_dir, paths_only=True,
        )
        return [(str(p), i + 1) for i, p in enumerate(pages)]
    except Exception as exc:
        logger.error("Error al rasterizar PDF '%s': %s", pdf_path, exc)
        return []


def _trocr_available() -> bool:
    try:
        from core.inkcore.glyph_labelers.trocr_labeler import TrOCRLabeler
        return bool(TrOCRLabeler.available)
    except Exception:
        return False


class BulkCaptureRunner:
    """Ejecuta la captura masiva sobre una lista de fuentes (imágenes + PDFs)."""

    def __init__(
        self,
        pipeline_config,
        progress_cb: Callable[[float, str], None] | None = None,
        cancel_event=None,
    ):
        self._cfg = pipeline_config
        self._progress = progress_cb or (lambda f, m: None)
        self._cancel_event = cancel_event

    def run(self, sources: list[str]) -> BulkCaptureSession:
        session = BulkCaptureSession(sources=list(sources), pipeline_config=self._cfg)
        t_start = time.perf_counter()

        # Paso 1: expandir PDFs a páginas
        image_pages: list[tuple[str, str, int]] = []
        for src in sources:
            if Path(src).suffix.lower() == ".pdf":
                rasterized = _rasterize_pdf(src, dpi=200)
                for img_path, pnum in rasterized:
                    image_pages.append((img_path, Path(src).name, pnum))
            else:
                image_pages.append((src, Path(src).name, 1))

        if not image_pages:
            return session

        # Paso 2: extraer glifos por imagen
        from core.inkcore.extraction_pipeline import GlyphExtractionPipeline
        extracted_per_page: list[tuple[str, int, list[GlyphEntry]]] = []
        total = len(image_pages)
        for i, (img, label, pnum) in enumerate(image_pages):
            if self._cancel_event and self._cancel_event.is_set():
                logger.info("BulkCaptureRunner: cancelado en imagen %d/%d", i + 1, total)
                break
            self._progress(i / total, f"Extrayendo {label} pág {pnum}…")
            try:
                pipeline = GlyphExtractionPipeline(self._cfg)
                result = pipeline.extract(img)
                extracted_per_page.append((img, pnum, result.glyphs))
                logger.debug("bulk: %s pág %d → %d glifos", label, pnum, len(result.glyphs))
            except Exception as exc:
                logger.error("bulk_runner: error en '%s' pág %d: %s", label, pnum, exc)
                extracted_per_page.append((img, pnum, []))

        # Paso 3: TrOCR post-labeling si el pipeline no lo usó ya
        _pipeline_already_labeled = bool(
            self._cfg
            and hasattr(self._cfg, "labelers")
            and "trocr_labeler" in (self._cfg.labelers or [])
        )
        if not _pipeline_already_labeled and _trocr_available():
            all_glyphs = [g for _, _, glyphs in extracted_per_page for g in glyphs]
            unlabeled = [g for g in all_glyphs if g.predicted_char is None]
            if unlabeled:
                self._progress(0.9, f"TrOCR: etiquetando {len(unlabeled)} glifos…")
                try:
                    from PIL import Image as _PIL
                    from core.inkcore.glyph_labelers.trocr_labeler import TrOCRLabeler
                    labeler = TrOCRLabeler()
                    if labeler.available:
                        crops: list = []
                        for g in unlabeled:
                            try:
                                crops.append(_PIL.open(g.image_path).convert("RGB"))
                            except Exception:
                                crops.append(_PIL.new("RGB", (32, 32), (255, 255, 255)))
                        results = labeler.label_batch(crops)
                        for g, (text, conf) in zip(unlabeled, results):
                            g.predicted_char = text[:1] if text and text != "?" else ""
                            g.label_confidence = conf
                        logger.info("TrOCR etiquetó %d glifos", len(unlabeled))
                except Exception as exc:
                    logger.warning("TrOCR post-labeling falló: %s", exc)

        # Paso 4: construir candidatos
        for img, pnum, glyphs in extracted_per_page:
            for g in glyphs:
                session.candidates.append(BulkGlyphCandidate(
                    glyph=g,
                    source_image=img,
                    source_page_num=pnum,
                ))

        elapsed = time.perf_counter() - t_start
        s = session.stats()
        try:
            from core.diagnostics import diagnostics
            diagnostics.log_event("bulk_capture", "session_complete", {
                "sources": len(session.sources),
                "extracted": s["total"],
                "approved": s["approved"],
                "rejected": s["rejected"],
                "elapsed_s": round(elapsed, 2),
            })
        except Exception:
            pass

        self._progress(1.0, f"Listo — {s['total']} glifos extraídos")
        return session
