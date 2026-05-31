"""Serialización GlyphEntry ↔ dict del manifest (extraído de bank.py en v4.2).

Lógica pura de ida/vuelta entre un GlyphEntry y su forma de diccionario en el
_manifest.json. Vive aparte para mantener bank.py por debajo de ~420 líneas;
GlyphBank._to_dict/_from_dict delegan acá.
"""

import logging

from core.models import GlyphEntry

logger = logging.getLogger(__name__)

_TIER_NORMALIZE = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze"}


def entry_to_dict(e: GlyphEntry) -> dict:
    return e.__dict__.copy()


def entry_from_dict(d: dict) -> GlyphEntry:
    # BUG-29: normalizar tier legacy + loguear campos faltantes para diagnóstico
    missing = [k for k in ("char", "image_path", "quality_score", "tier") if k not in d]
    if missing:
        logger.warning(
            "Manifest entry incompleto (faltan %s) — usando defaults para %s",
            missing, d.get("image_path", "?"),
        )
    entry = GlyphEntry()
    for k, v in d.items():
        if k == "tier" and isinstance(v, str):
            v = _TIER_NORMALIZE.get(v.lower(), v)
        if hasattr(entry, k):
            setattr(entry, k, v)
    return entry
