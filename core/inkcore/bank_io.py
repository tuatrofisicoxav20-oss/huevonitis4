"""I/O del banco: scan de PNGs y backfill de hashes (extraído de bank.py en v4.2).

Lógica de filesystem que construye/repara entries a partir de los PNGs del
banco. Vive aparte para mantener bank.py por debajo de ~420 líneas. Las
funciones son puras respecto del manifest: NO llaman save(); GlyphBank decide
cuándo persistir (los wrappers en bank.py conservan ese save()).
"""

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path

from core.inkcore.bank_hashing import PIL_OK, _dhash
from core.inkcore.quality import assess_glyph
from core.models import GlyphEntry

logger = logging.getLogger(__name__)

if PIL_OK:
    from PIL import Image


def scan_existing(bank_dir: Path, profile_id: str) -> list[GlyphEntry]:
    """Reconstruye los entries escaneando los PNGs sueltos del banco.

    Se usa cuando no hay manifest (banco nuevo) o está corrupto. NO persiste:
    el caller hace save() después.
    """
    entries: list[GlyphEntry] = []
    for png in sorted(bank_dir.glob("*.png")):
        stem = png.stem
        parts = stem.rsplit("_", 1)
        if len(parts) == 2:
            char = parts[0]
            if char.startswith("punct_"):
                with contextlib.suppress(Exception):
                    char = chr(int(char[6:]))
            try:
                idx = int(parts[1])
            except ValueError:
                idx = 0
            metrics = assess_glyph(str(png))
            # PERF-02/07: computar hash de una vez con context-managed PIL
            ph = ""
            if PIL_OK:
                try:
                    with Image.open(png) as raw:
                        ph = _dhash(raw.convert("RGBA"))
                except Exception:
                    pass
            entries.append(GlyphEntry(
                char=char,
                image_path=str(png),
                quality_score=metrics["score"],
                tier=metrics["tier"],
                ink_coverage=metrics["ink_coverage"],
                index=idx,
                profile_id=profile_id,
                perceptual_hash=ph,
            ))
    return entries


def backfill_missing_hashes(
    entries: list[GlyphEntry],
    is_degenerate: Callable[[str], bool],
) -> int:
    """Recalcula perceptual_hash de entries sin hash o con hash degenerado.

    Cubre dos casos: bancos pre-v4.2 que no tenían hash, y bancos guardados
    con el _dhash roto que colapsaba a '000…0' (ver _glyph_to_gray). En ambos
    el dedup queda inservible hasta recomputar. Repara los entries IN PLACE y
    devuelve cuántos recibieron hash; el caller persiste si hubo cambios.
    """
    if not PIL_OK:
        return 0
    needs_hash = [e for e in entries if is_degenerate(e.perceptual_hash)]
    if not needs_hash:
        return 0
    rebuilt = 0
    for e in needs_hash:
        try:
            with Image.open(e.image_path) as raw:
                e.perceptual_hash = _dhash(raw.convert("RGBA"))
            rebuilt += 1
        except Exception as exc:
            logger.warning(
                "_backfill_missing_hashes: %s falló: %s", e.image_path, exc,
            )
    if rebuilt:
        logger.info(
            "_backfill_missing_hashes: %d/%d entries recibieron hash; guardando manifest",
            rebuilt, len(needs_hash),
        )
    return rebuilt
