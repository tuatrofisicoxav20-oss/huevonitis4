"""Thumbnails persistentes para los grids del banco (U4/UI-05).

Lógica pura y testeable (cero Tk): los thumbs viven en
``{bank_dir}/.thumbs/{size}/{hash}.png`` (RGBA, lado máx = size) y se
invalidan por mtime del PNG fuente. Los grids de la UI consumen SOLO estos
thumbs — nunca el PNG completo en caliente.

También expone diff_paths(), el corazón del refresh diferencial del grid
(qué celdas crear/destruir/conservar entre dos estados del banco).
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False

DEFAULT_SIZE = 64


def thumb_dir(bank_dir: Path | str, size: int = DEFAULT_SIZE) -> Path:
    return Path(bank_dir) / ".thumbs" / str(size)


def thumb_path(bank_dir: Path | str, src: Path | str,
               size: int = DEFAULT_SIZE) -> Path:
    """Ruta determinista del thumb de `src` (hash de la ruta absoluta)."""
    digest = hashlib.sha1(str(Path(src).resolve()).encode("utf-8")).hexdigest()[:16]
    return thumb_dir(bank_dir, size) / f"{digest}.png"


def is_stale(src: Path, tpath: Path) -> bool:
    """True si el thumb falta o es más viejo que el PNG fuente."""
    try:
        if not tpath.exists():
            return True
        return tpath.stat().st_mtime < src.stat().st_mtime
    except OSError:
        return True


def ensure_thumb(bank_dir: Path | str, src: Path | str,
                 size: int = DEFAULT_SIZE) -> Path | None:
    """Devuelve la ruta del thumb, generándolo si falta o quedó stale.

    None si la fuente no existe o PIL no está disponible.
    """
    if not PIL_OK:
        return None
    src = Path(src)
    if not src.exists():
        return None
    tpath = thumb_path(bank_dir, src, size)
    if not is_stale(src, tpath):
        return tpath
    try:
        tpath.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as f:
            img = f.convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        img.save(tpath)
        return tpath
    except Exception as exc:
        logger.warning("thumb_cache: no se pudo generar thumb de %s: %s", src, exc)
        return None


def build_thumbs(bank_dir: Path | str, sources, size: int = DEFAULT_SIZE,
                 progress_cb=None, should_cancel=None) -> int:
    """Genera en lote los thumbs que falten. Pensado para un worker thread.

    progress_cb(done, total) se llama por item; should_cancel() corta el
    lote. Devuelve cuántos thumbs se (re)generaron.
    """
    sources = list(sources)
    total = len(sources)
    generated = 0
    for i, src in enumerate(sources, 1):
        if should_cancel is not None and should_cancel():
            break
        src = Path(src)
        tpath = thumb_path(bank_dir, src, size)
        if src.exists() and is_stale(src, tpath) and ensure_thumb(bank_dir, src, size):
            generated += 1
        if progress_cb is not None:
            with contextlib.suppress(Exception):
                progress_cb(i, total)
    return generated


def prune_orphans(bank_dir: Path | str, sources, size: int = DEFAULT_SIZE) -> int:
    """Borra thumbs cuyo PNG fuente ya no está en el banco."""
    tdir = thumb_dir(bank_dir, size)
    if not tdir.is_dir():
        return 0
    valid = {thumb_path(bank_dir, s, size).name for s in sources}
    removed = 0
    for f in tdir.glob("*.png"):
        if f.name not in valid:
            with contextlib.suppress(OSError):
                f.unlink()
                removed += 1
    return removed


def diff_paths(old: set, new: set) -> tuple[set, set, set]:
    """Diff del grid: (a_crear, a_destruir, a_conservar) por image_path."""
    old, new = set(old), set(new)
    return new - old, old - new, old & new
