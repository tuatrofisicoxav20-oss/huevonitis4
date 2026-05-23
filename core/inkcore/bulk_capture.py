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
    source_label: str = ""  # nombre legible para mostrar, ej. "Página 3"

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
    is_pdf: bool = False
    total_pages: int = 0
    elapsed_s: float = 0.0

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
        pdf_dpi: int = 300,
    ):
        self._cfg = pipeline_config
        self._progress = progress_cb or (lambda f, m: None)
        self._cancel_event = cancel_event
        self._dpi = pdf_dpi

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

    def run_pdf(self, pdf_path: str) -> BulkCaptureSession:
        """Procesa un PDF escaneado, 2 páginas a la vez para limitar RAM."""
        try:
            from pdf2image import convert_from_path, pdfinfo_from_path
        except ImportError:
            logger.error("pdf2image no disponible — no se puede procesar el PDF")
            return BulkCaptureSession(sources=[pdf_path], is_pdf=True)

        t0 = time.perf_counter()

        try:
            info = pdfinfo_from_path(pdf_path)
            total_pages = int(info["Pages"])
        except Exception as exc:
            logger.error("pdfinfo_from_path falló: %s", exc)
            return BulkCaptureSession(sources=[pdf_path], is_pdf=True)

        session = BulkCaptureSession(
            sources=[pdf_path],
            is_pdf=True,
            total_pages=total_pages,
            pipeline_config=self._cfg,
        )

        BATCH = 2  # 2 páginas a 300 DPI ≈ 60 MB en RAM
        for batch_start in range(1, total_pages + 1, BATCH):
            if self._cancel_event and self._cancel_event.is_set():
                logger.info("run_pdf: cancelado en pág %d", batch_start)
                break

            batch_end = min(batch_start + BATCH - 1, total_pages)
            self._progress(
                (batch_start - 1) / total_pages * 0.75,
                f"Rasterizando páginas {batch_start}–{batch_end} de {total_pages}…",
            )

            try:
                imgs = convert_from_path(
                    pdf_path, dpi=self._dpi,
                    first_page=batch_start, last_page=batch_end,
                )
            except Exception as exc:
                logger.error("convert_from_path pág %d-%d: %s", batch_start, batch_end, exc)
                continue

            for offset, pil_img in enumerate(imgs):
                page_num = batch_start + offset
                if self._cancel_event and self._cancel_event.is_set():
                    pil_img.close()
                    break

                tmp_path = self._save_temp(pil_img, page_num)
                pil_img.close()

                frac = ((batch_start - 1 + offset + 0.5) / total_pages) * 0.75
                self._progress(frac, f"Extrayendo glifos página {page_num}/{total_pages}…")

                glyphs = self._extract_from_image(tmp_path)
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

                for g in glyphs:
                    session.candidates.append(BulkGlyphCandidate(
                        glyph=g,
                        source_image=tmp_path,
                        source_page_num=page_num,
                        source_label=f"Página {page_num}",
                    ))

            del imgs

        # TrOCR post-labeling si el pipeline no lo hizo
        _pipeline_labeled = bool(
            self._cfg and hasattr(self._cfg, "labelers")
            and "trocr_labeler" in (self._cfg.labelers or [])
        )
        if not _pipeline_labeled and _trocr_available():
            unlabeled = [c.glyph for c in session.candidates if c.glyph.predicted_char is None]
            if unlabeled:
                self._progress(0.8, f"TrOCR: etiquetando {len(unlabeled)} glifos…")
                try:
                    from PIL import Image as _PIL
                    from core.inkcore.glyph_labelers.trocr_labeler import TrOCRLabeler
                    labeler = TrOCRLabeler()
                    if labeler.available:
                        crops = []
                        for g in unlabeled:
                            try:
                                crops.append(_PIL.open(g.image_path).convert("RGB"))
                            except Exception:
                                crops.append(_PIL.new("RGB", (32, 32), (255, 255, 255)))
                        BATCH_LBL = 32
                        for start in range(0, len(crops), BATCH_LBL):
                            if self._cancel_event and self._cancel_event.is_set():
                                break
                            chunk = crops[start:start + BATCH_LBL]
                            results = labeler.label_batch(chunk)
                            for g, (text, conf) in zip(
                                unlabeled[start:start + BATCH_LBL], results
                            ):
                                g.predicted_char = text[:1] if text and text != "?" else ""
                                g.label_confidence = conf
                            done = min(start + BATCH_LBL, len(crops))
                            self._progress(
                                0.8 + 0.18 * done / max(1, len(crops)),
                                f"TrOCR: {done}/{len(crops)}…",
                            )
                        for img in crops:
                            img.close()
                except Exception as exc:
                    logger.warning("TrOCR post-labeling en run_pdf falló: %s", exc)

        session.elapsed_s = time.perf_counter() - t0
        s = session.stats()
        self._progress(1.0, f"Listo — {s['total']} glifos en {session.elapsed_s:.1f}s")
        logger.info(
            "run_pdf: %d glifos de %d págs en %.1fs", s["total"], total_pages, session.elapsed_s
        )
        return session

    def run_images(self, image_paths: list[str]) -> BulkCaptureSession:
        """Procesa una lista de imágenes (caso sin PDF)."""
        return self.run(image_paths)

    def _extract_from_image(self, img_path: str) -> list[GlyphEntry]:
        from core.inkcore.extraction_pipeline import GlyphExtractionPipeline
        try:
            pipeline = GlyphExtractionPipeline(self._cfg)
            result = pipeline.extract(img_path)
            return result.glyphs
        except Exception as exc:
            logger.error("_extract_from_image '%s': %s", img_path, exc)
            return []

    def _save_temp(self, pil_img: "object", page_num: int) -> str:
        import config
        temp_dir = config.DATA_DIR / "temp_bulk_capture"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / f"page_{page_num}_{id(pil_img)}.png"
        pil_img.save(str(path), "PNG")
        return str(path)
