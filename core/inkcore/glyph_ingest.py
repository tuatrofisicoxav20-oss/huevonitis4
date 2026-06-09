"""glyph_ingest: motor mínimo de procesamiento de imagen para la captura de glifos.

Reúne las primitivas que la Captura masiva (``extraction_pipeline``) y la Plantilla
(``template_extract``) necesitan, desacopladas de la fachada ``GlyphExtractor`` del
extractor viejo (eliminado en la limpieza v4.2). El motor real vive en
``extractor_preprocess`` (preprocesado: escala, autocrop, deskew, binarización) y en
``extractor_glyph_ops`` (recorte/refinado/quality del glifo); este módulo solo los
agrupa con una API limpia y sin tentáculos del extractor legacy.

Antes este preprocesado se obtenía instanciando ``GlyphExtractor()`` y llamando sus
métodos privados (``_scale``, ``_autocrop``, ``_deskew``, ``_full_preprocess``,
``_refine_char_region``, ``_tight_crop``, ``_to_rgba_smooth``, ``_assess_quality``).
Eso arrastraba todo el extractor viejo (alineación, estrategias, auto_text/TrOCR);
ahora se usa directo el motor de imagen.
"""
from __future__ import annotations

import logging
from pathlib import Path

# Re-export del motor de imagen real (módulos VIVOS, no tocar).
from core.inkcore.extractor_glyph_ops import (
    assess_quality,
    refine_char_region,
    tight_crop,
    to_rgba_smooth,
)
from core.inkcore.extractor_preprocess import (
    ImagePreprocessor,
    imread_oriented,
    orient_by_content,
)

__all__ = [
    "GlyphPreprocessOptions",
    "ImagePreprocessor",
    "assess_quality",
    "imread_oriented",
    "orient_by_content",
    "purge_temp_pngs",
    "refine_char_region",
    "tight_crop",
    "to_rgba_smooth",
]

logger = logging.getLogger(__name__)


class GlyphPreprocessOptions:
    """Opciones mínimas para ``ImagePreprocessor.full_preprocess``.

    ``full_preprocess`` solo lee ``remove_lines``; ``min_quality`` se conserva por
    si el caller lo necesita aguas abajo (la Captura lo pasa desde su config).
    Reemplaza al antiguo ``ExtractionOptions`` para no depender de ``extractor.py``.
    """

    __slots__ = ("min_quality", "remove_lines")

    def __init__(self, *, remove_lines: bool = True, min_quality: float = 0.0):
        self.remove_lines = remove_lines
        self.min_quality = min_quality


def purge_temp_pngs(temp_dir: Path) -> int:
    """Borra los PNG residuales de ``_temp_extract`` antes de una extracción nueva.

    Cada extracción reemplaza a la anterior en la UI, así que los temporales de una
    extracción que no se guardó quedan huérfanos y solo acumulan disco. El cleanup
    selectivo de ``save_glyphs_to_bank`` solo borra los que SÍ se guardaron; limpiar
    aquí, al inicio, evita que crezcan sin límite. (La Captura masiva usa otro dir.)

    Movido desde ``extractor._purge_temp_pngs`` en la limpieza v4.2.
    """
    removed = 0
    for png in temp_dir.glob("*.png"):
        try:
            png.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("purge_temp_pngs: no se pudo borrar %s: %s", png, exc)
    if removed:
        logger.info("purge_temp_pngs: %d temporal(es) huérfano(s) descartado(s)", removed)
    return removed
