"""
Captura masiva de glifos: procesa múltiples imágenes/PDFs en lote,
devuelve candidatos listos para revisión y aprobación al banco.
"""
from __future__ import annotations

import contextlib
import logging
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core.models import GlyphEntry

logger = logging.getLogger(__name__)

# Extensiones que run_folder reconoce como fuentes válidas (imágenes + PDF).
# Coincide con lo que run() sabe expandir: los .pdf se rasterizan a páginas y
# el resto se trata como imagen individual.
SUPPORTED_SOURCE_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf",
})


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


def _rasterize_pdf(
    pdf_path: str, dpi: int = 200, *, tracker: list[str] | None = None,
) -> list[tuple[str, int]]:
    """BUG-04: si tracker se pasa (lista), registra el tmp_dir creado para
    cleanup posterior. Sin esto, /tmp se llena con 10-50 MB por página
    hasta reboot."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logger.warning("pdf2image no disponible — saltando PDF '%s'", pdf_path)
        return []
    tmp_dir = tempfile.mkdtemp(prefix="bulk_raster_")
    if tracker is not None:
        tracker.append(tmp_dir)
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
        # Pipeline lazy-init: lo creamos UNA vez y reusamos en todas las
        # imágenes (antes se re-creaba por iteración → recargaba modelos).
        self._pipeline = None
        # BUG-04: tracker de tmp_dirs creados por _rasterize_pdf — se limpian
        # en _cleanup_raster_tmps() al final de run() / run_pdf().
        self._raster_tmp_dirs: list[str] = []

    def _cleanup_raster_tmps(self) -> None:
        """Borra los tmp_dirs creados por _rasterize_pdf en esta sesión."""
        import shutil
        for d in self._raster_tmp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception as exc:
                logger.warning("No se pudo borrar tmp_dir %s: %s", d, exc)
        self._raster_tmp_dirs.clear()

    def _get_pipeline(self):
        if self._pipeline is None:
            from core.inkcore.extraction_pipeline import GlyphExtractionPipeline
            self._pipeline = GlyphExtractionPipeline(self._cfg)
        return self._pipeline

    def run(self, sources: list[str]) -> BulkCaptureSession:
        session = BulkCaptureSession(sources=list(sources), pipeline_config=self._cfg)
        t_start = time.perf_counter()

        # Paso 1: expandir PDFs a páginas
        image_pages: list[tuple[str, str, int]] = []
        for src in sources:
            if Path(src).suffix.lower() == ".pdf":
                # BUG-04: pasar tracker para cleanup al final
                rasterized = _rasterize_pdf(src, dpi=200, tracker=self._raster_tmp_dirs)
                for img_path, pnum in rasterized:
                    image_pages.append((img_path, Path(src).name, pnum))
            else:
                image_pages.append((src, Path(src).name, 1))

        if not image_pages:
            return session

        # Paso 2: extraer glifos por imagen — paralelizado.
        # cv2 libera el GIL en las operaciones pesadas, así que ThreadPool
        # da speed-up real (3-6× en máquinas multi-core). Reusamos el mismo
        # GlyphExtractionPipeline en todos los threads (sus métodos son
        # idempotentes para una misma config).
        extracted_per_page: list[tuple[str, int, list[GlyphEntry]]] = []
        total = len(image_pages)
        done_counter = {"n": 0}
        counter_lock = threading.Lock()

        def _work(idx_img_label_pnum):
            _i, (img, label, pnum) = idx_img_label_pnum
            if self._cancel_event and self._cancel_event.is_set():
                return (img, pnum, [])
            try:
                result = self._get_pipeline().extract(img)
                glyphs = result.glyphs
            except Exception as exc:
                logger.error("bulk_runner: error en '%s' pág %d: %s", label, pnum, exc)
                glyphs = []
            with counter_lock:
                done_counter["n"] += 1
                self._progress(done_counter["n"] / total,
                               f"Extrayendo {label} pág {pnum}…")
            return (img, pnum, glyphs)

        max_workers = min(4, max(1, total))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(_work, enumerate(image_pages)):
                extracted_per_page.append(result)
                logger.debug("bulk: %s → %d glifos", result[0], len(result[2]))

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
                        for g, (text, conf) in zip(unlabeled, results, strict=False):
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
        # BUG-04: limpiar tmp_dirs de rasterización
        self._cleanup_raster_tmps()
        return session

    def run_folder(
        self,
        folder: str,
        *,
        recursive: bool = False,
    ) -> BulkCaptureSession:
        """Procesa todas las imágenes/PDFs de una carpeta en lote.

        Recolecta las fuentes con extensión en SUPPORTED_SOURCE_EXTS (ignora
        mayúsculas/minúsculas), las ordena por nombre para que el orden sea
        determinista y delega en run(). Con recursive=True desciende a
        subcarpetas.

        Devuelve una BulkCaptureSession vacía si la ruta no es una carpeta o no
        contiene fuentes reconocidas.
        """
        root = Path(folder)
        if not root.is_dir():
            logger.warning("run_folder: '%s' no es una carpeta", folder)
            return BulkCaptureSession(sources=[], pipeline_config=self._cfg)

        walker = root.rglob("*") if recursive else root.glob("*")
        sources = sorted(
            str(p) for p in walker
            if p.is_file() and p.suffix.lower() in SUPPORTED_SOURCE_EXTS
        )
        if not sources:
            logger.warning(
                "run_folder: no se encontraron imágenes/PDFs en '%s'%s",
                folder, " (recursivo)" if recursive else "",
            )
            return BulkCaptureSession(sources=[], pipeline_config=self._cfg)

        logger.info("run_folder: %d fuentes en '%s'", len(sources), folder)
        return self.run(sources)

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
                with contextlib.suppress(Exception):
                    Path(tmp_path).unlink(missing_ok=True)

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
                                unlabeled[start:start + BATCH_LBL], results, strict=False
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

    def _extract_from_image(self, img_path: str) -> list[GlyphEntry]:
        try:
            result = self._get_pipeline().extract(img_path)
            return result.glyphs
        except Exception as exc:
            logger.error("_extract_from_image '%s': %s", img_path, exc)
            return []

    def _save_temp(self, pil_img: object, page_num: int) -> str:
        import config
        temp_dir = config.DATA_DIR / "temp_bulk_capture"
        temp_dir.mkdir(exist_ok=True)
        path = temp_dir / f"page_{page_num}_{id(pil_img)}.png"
        pil_img.save(str(path), "PNG")
        return str(path)
