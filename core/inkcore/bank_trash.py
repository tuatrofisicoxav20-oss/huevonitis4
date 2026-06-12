"""Papelera del banco de glifos (U9-F4) — lógica pura, sin tkinter.

Borrado en dos pasos para el banco: en lugar de eliminar glifos para siempre,
``trash_glyphs`` los mueve a ``{bank_dir}/.trash/{timestamp}/`` junto con un
``manifest.json`` que serializa las entradas completas, de modo que
``restore_trash`` pueda devolverlas al banco tal cual (mismo char, tier,
score y geometría). ``list_trash`` y ``empty_trash`` administran las papeleras.

Decisiones de diseño (leídas del código de bank.py):
  • ``GlyphBank.remove_glyph`` hace ``unlink()`` del PNG si existe bajo
    bank_dir. Por eso el PNG se MUEVE a la papelera ANTES de llamarlo: al no
    existir ya el archivo, remove_glyph se salta el borrado y solo quita la
    entrada del manifest del banco (con sus locks de siempre).
  • ``.trash/`` vive dentro de bank_dir pero no contamina nada: tanto el load
    del manifest como ``bank_io.scan_existing`` (glob ``*.png`` NO recursivo)
    ignoran subdirectorios.
  • La restauración usa ``add_glyph`` (API pública, respeta locks y dedup) con
    ``quality_override`` + ``skip_dedup=True`` + ``geometry`` para preservar
    tier/score/métricas sin recalcular ni rechazar por duplicado perceptual.
"""

import json
import logging
import shutil
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.inkcore.bank_serial import entry_from_dict, entry_to_dict

if TYPE_CHECKING:
    from core.inkcore.bank import GlyphBank
    from core.models import GlyphEntry

logger = logging.getLogger(__name__)

# Nombre del directorio raíz de papeleras dentro de bank_dir. Con punto inicial
# para que quede oculto y fuera de cualquier listado casual del banco.
_TRASH_DIRNAME = ".trash"
_TRASH_MANIFEST = "manifest.json"

# Campos de geometría (R1) que add_glyph acepta vía su kwarg ``geometry``.
_GEOMETRY_FIELDS = ("nat_h_px", "nat_w_px", "baseline_off", "em_px", "lsb", "rsb", "metrics_source")


def _trash_root(bank_dir: "Path | str") -> Path:
    """Directorio raíz de papeleras de un banco: {bank_dir}/.trash/."""
    return Path(bank_dir) / _TRASH_DIRNAME


def trash_glyphs(bank: "GlyphBank", entries: "Iterable[GlyphEntry]") -> "str | None":
    """Mueve glifos del banco a una papelera nueva. Devuelve su id o None.

    Crea ``{bank.bank_dir}/.trash/{timestamp}/``, mueve ahí los PNG y escribe
    un ``manifest.json`` con la serialización completa de cada entrada (la
    misma de bank_serial, para que restore_trash las reconstruya idénticas).
    Las entradas se quitan del banco vía ``remove_glyph`` (API pública: locks
    e índices quedan consistentes); como el PNG ya fue movido, remove_glyph
    no borra nada del disco.

    Devuelve el id de la papelera (nombre del directorio timestamp) o None si
    ``entries`` estaba vacío o ningún glifo pudo moverse.
    """
    entries = list(entries)
    if not entries:
        return None
    trash_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    trash_dir = _trash_root(bank.bank_dir) / trash_id
    trash_dir.mkdir(parents=True, exist_ok=True)

    moved: list[dict] = []
    # begin/end_batch: difiere el save() del manifest del banco a UN solo write
    # al final, en vez de uno por cada remove_glyph.
    bank.begin_batch()
    try:
        for entry in entries:
            src = Path(entry.image_path)
            d = entry_to_dict(entry)
            if src.exists():
                dest = trash_dir / src.name  # basenames únicos dentro de bank_dir
                try:
                    shutil.move(str(src), str(dest))
                except OSError as exc:
                    logger.warning("trash_glyphs: no se pudo mover %s: %s", src, exc)
                    continue  # no se quita del banco: el glifo sigue íntegro
                d["_trash_file"] = dest.name
            else:
                # PNG ya desaparecido del disco: se conserva solo la metadata
                # (restore la saltará) pero la entrada huérfana sí sale del banco.
                d["_trash_file"] = None
            moved.append(d)
            # MOVER ANTES, REMOVER DESPUÉS: ver docstring del módulo.
            bank.remove_glyph(entry)
    finally:
        bank.end_batch()

    if not moved:
        shutil.rmtree(trash_dir, ignore_errors=True)
        return None
    manifest = {"created": time.time(), "profile_id": bank.profile_id, "entries": moved}
    (trash_dir / _TRASH_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("trash_glyphs: %d glifo(s) → papelera %s", len(moved), trash_id)
    return trash_id


def restore_trash(bank: "GlyphBank", trash_id: str) -> int:
    """Restaura al banco los glifos de la papelera ``trash_id``.

    Reconstruye cada entrada desde el manifest de la papelera y la re-agrega
    vía ``bank.add_glyph`` (API pública) preservando char, tier, score,
    metadatos del pipeline y geometría; ``skip_dedup=True`` garantiza que un
    glifo parecido a otro del banco no sea rechazado al volver. Al terminar
    borra el directorio de la papelera.

    Devuelve cuántos glifos se restauraron (0 si la papelera no existe).
    """
    trash_dir = _trash_root(bank.bank_dir) / trash_id
    manifest_path = trash_dir / _TRASH_MANIFEST
    if not manifest_path.exists():
        logger.warning("restore_trash: papelera %s sin manifest — nada que restaurar", trash_id)
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("restore_trash: manifest corrupto en %s: %s", trash_dir, exc)
        return 0

    restored = 0
    bank.begin_batch()
    try:
        for d in data.get("entries", []):
            fname = d.get("_trash_file")
            if not fname or not (trash_dir / fname).exists():
                continue  # entrada sin PNG: no hay nada que restaurar
            entry = entry_from_dict({k: v for k, v in d.items() if not k.startswith("_")})
            new = bank.add_glyph(
                entry.char,
                str(trash_dir / fname),
                predicted_char=entry.predicted_char,
                label_confidence=entry.label_confidence,
                detector_sources=entry.detector_sources,
                quality_override={
                    "score": entry.quality_score,
                    "tier": entry.tier,
                    "ink_coverage": entry.ink_coverage,
                },
                skip_dedup=True,
                geometry={k: getattr(entry, k) for k in _GEOMETRY_FIELDS},
            )
            if new is not None:
                restored += 1
    finally:
        bank.end_batch()

    shutil.rmtree(trash_dir, ignore_errors=True)
    logger.info("restore_trash: %d glifo(s) restaurados desde %s", restored, trash_id)
    return restored


def list_trash(bank_dir: "Path | str") -> list[dict]:
    """Lista las papeleras existentes de un banco, más reciente primero.

    Devuelve una lista de dicts ``{"id", "timestamp", "count"}``: el id es el
    nombre del directorio, timestamp es epoch (del manifest, o mtime del
    directorio como fallback) y count el nº de glifos guardados.
    """
    root = _trash_root(bank_dir)
    if not root.is_dir():
        return []
    out: list[dict] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        ts = d.stat().st_mtime
        count = None
        mp = d / _TRASH_MANIFEST
        if mp.exists():
            try:
                data = json.loads(mp.read_text(encoding="utf-8"))
                count = len(data.get("entries", []))
                ts = float(data.get("created", ts))
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                count = None  # manifest ilegible → contar PNGs abajo
        if count is None:
            count = len(list(d.glob("*.png")))
        out.append({"id": d.name, "timestamp": ts, "count": count})
    out.sort(key=lambda x: x["timestamp"], reverse=True)
    return out


def empty_trash(bank_dir: "Path | str", older_than_s: "float | None" = None) -> int:
    """Borra papeleras definitivamente. Devuelve cuántas borró.

    Con ``older_than_s=None`` borra TODAS; con un número, solo las que tengan
    más de esos segundos de antigüedad (para purgas automáticas tipo
    "vaciar papeleras de más de 30 días").
    """
    root = _trash_root(bank_dir)
    if not root.is_dir():
        return 0
    now = time.time()
    removed = 0
    for info in list_trash(bank_dir):
        if older_than_s is not None and (now - info["timestamp"]) < older_than_s:
            continue
        shutil.rmtree(root / info["id"], ignore_errors=True)
        removed += 1
    if removed:
        logger.info("empty_trash: %d papelera(s) eliminadas de %s", removed, root)
    return removed
