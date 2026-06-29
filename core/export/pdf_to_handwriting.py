"""Convierte un PDF existente (texto o escaneado) a un PDF con la letra del
usuario, listo para imprimir.

Wayland-safe y sin dependencias Python nuevas: la extracción de texto usa las
herramientas de Poppler (``pdftotext`` / ``pdftoppm``) y ``tesseract``, que ya
son dependencias de sistema del proyecto (ver tools/doctor.py). Esto evita el
camino de OCREngine, que en algunos venv carece de pdfplumber/pdf2image.

Pipeline: extraer texto del PDF -> renderizar con el banco de glifos del
usuario -> exportar PDF. Devuelve un dict con la ruta de salida, el conteo de
páginas y un reporte de cobertura (qué caracteres se omitieron por no tener
glifo en el banco), para que la UI/CLI no sorprenda al usuario con huecos.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Si pdftotext devuelve menos de esto, asumimos PDF escaneado (imágenes) y
# caemos a OCR con tesseract.
_MIN_TEXT_CHARS = 20


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def extract_pdf_text(pdf_path: str | Path, lang: str = "spa+eng") -> str:
    """Extrae el texto de un PDF.

    1) ``pdftotext`` (Poppler): exacto e instantáneo para PDFs con texto.
    2) Si sale (casi) vacío -> PDF escaneado: ``pdftoppm`` a PNG 300 DPI +
       ``tesseract`` por página.

    Lanza RuntimeError si no hay herramientas, o ValueError si no se pudo
    extraer texto de ninguna forma.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"No existe el PDF: {pdf_path}")

    # --- 1) Texto digital con pdftotext ---
    if _have("pdftotext"):
        try:
            out = subprocess.run(
                ["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
                capture_output=True, timeout=120, check=False,
            )
            text = out.stdout.decode("utf-8", errors="replace").strip()
            if len(text) >= _MIN_TEXT_CHARS:
                logger.info("extract_pdf_text: pdftotext -> %d chars", len(text))
                return text
        except Exception as exc:
            logger.warning("pdftotext falló: %s", exc)
    else:
        logger.warning("pdftotext (poppler) no está en PATH")

    # --- 2) Escaneado: pdftoppm + tesseract ---
    if _have("pdftoppm") and _have("tesseract"):
        logger.info("extract_pdf_text: parece escaneado, usando OCR (tesseract)")
        with tempfile.TemporaryDirectory(prefix="h4_pdf2hw_") as td:
            prefix = str(Path(td) / "pg")
            try:
                subprocess.run(
                    ["pdftoppm", "-r", "300", "-png", str(pdf_path), prefix],
                    capture_output=True, timeout=600, check=True,
                )
            except Exception as exc:
                raise ValueError(f"No se pudo rasterizar el PDF: {exc}") from exc
            pages = sorted(Path(td).glob("pg*.png"))
            chunks: list[str] = []
            for png in pages:
                try:
                    r = subprocess.run(
                        ["tesseract", str(png), "-", "-l", lang],
                        capture_output=True, timeout=300, check=False,
                    )
                    chunks.append(r.stdout.decode("utf-8", errors="replace"))
                except Exception as exc:
                    logger.warning("tesseract falló en %s: %s", png.name, exc)
            text = "\n".join(chunks).strip()
            if text:
                logger.info("extract_pdf_text: OCR -> %d chars (%d págs)",
                            len(text), len(pages))
                return text

    raise ValueError(
        "No se pudo extraer texto del PDF. Si es un PDF escaneado, instalá "
        "tesseract y poppler (pdftoppm)."
    )


def convert_pdf_to_handwriting(
    pdf_path: str | Path,
    renderer,
    options,
    out_path: str | Path,
    *,
    progress_cb=None,
    lang: str = "spa+eng",
) -> dict:
    """PDF existente -> PDF con la letra del usuario.

    renderer: HandwritingRenderer ya cargado (pipeline.renderer).
    options:  RenderOptions a usar para el render.
    out_path: ruta del PDF de salida.
    progress_cb(frac, msg): callback opcional de progreso (0..1).

    Devuelve dict: {out_path, n_pages, n_chars, missing, case_downgraded}.
    Lanza si algo falla (el llamador decide cómo avisar).
    """
    out_path = Path(out_path)

    if progress_cb:
        progress_cb(0.05, "Extrayendo texto del PDF…")
    text = extract_pdf_text(pdf_path, lang=lang)
    if not text.strip():
        raise ValueError("El PDF no contiene texto extraíble")

    # Cobertura: qué se va a omitir por falta de glifo (no sorprender al usuario)
    cov = {}
    try:
        cov = renderer.coverage_report(text)
    except Exception as exc:
        logger.warning("coverage_report falló: %s", exc)

    if progress_cb:
        progress_cb(0.35, "Renderizando con tu letra…")
    pages = renderer.render_pages(text, options)
    if not pages:
        raise ValueError("El render no produjo ninguna página")

    if progress_cb:
        progress_cb(0.85, "Exportando PDF…")
    from core.export.pdf_exporter import export_pages_streaming
    ok = export_pages_streaming(pages, str(out_path), page_size="letter")
    if not ok or not out_path.exists():
        raise RuntimeError("La exportación del PDF falló")

    if progress_cb:
        progress_cb(1.0, "Listo")
    return {
        "out_path": str(out_path),
        "n_pages": len(pages),
        "n_chars": len(text),
        "missing": cov.get("missing", []),
        "case_downgraded": cov.get("case_downgraded", []),
    }
