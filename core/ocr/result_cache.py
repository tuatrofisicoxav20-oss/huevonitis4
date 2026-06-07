"""
Caché en disco para resultados de ingestión OCR.

Clave: sha256(ruta_absoluta + mtime + tamaño + backend + opciones) → archivo .pkl
Versión de esquema: 2 — incluye backend y opciones en la clave.
Invalidación automática si el archivo fuente cambia o si el backend/opciones difieren.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import pickle
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_CACHE_VERSION = "2"
_VERSION_FILE = ".cache_version"


def _cache_key(source_path: str, backend_name: str, options_sig: str) -> str | None:
    """Devuelve la clave de caché, o None si no se puede leer el archivo fuente."""
    try:
        stat = os.stat(source_path)
        raw = (
            f"{os.path.abspath(source_path)}|{stat.st_mtime}|{stat.st_size}|"
            f"{backend_name}|{options_sig}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()
    except OSError:
        return None


class OCRResultCache:
    """Caché de resultados de OCR en disco bajo config.OCR_CACHE_DIR."""

    def __init__(self):
        self._cache_dir = config.OCR_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _migrate(self) -> None:
        """Borra entradas de versión anterior si el esquema de clave cambió."""
        version_file = self._cache_dir / _VERSION_FILE
        if version_file.exists():
            try:
                if version_file.read_text().strip() == _CACHE_VERSION:
                    return
            except OSError:
                pass
        # Versión incorrecta o ausente — purgar todo
        removed = 0
        for pkl in self._cache_dir.glob("*.pkl"):
            try:
                pkl.unlink()
                removed += 1
            except OSError:
                pass
        with contextlib.suppress(OSError):
            version_file.write_text(_CACHE_VERSION)
        if removed:
            logger.info("OCRResultCache: purga de migración (%d entradas v1)", removed)

    def _path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.pkl"

    def get(self, source_path: str, backend_name: str = "", options_sig: str = ""):
        """Devuelve el Document cacheado o None si no existe / expiró."""
        key = _cache_key(source_path, backend_name, options_sig)
        if key is None:
            return None
        pkl = self._path(key)
        if not pkl.exists():
            return None
        try:
            with pkl.open("rb") as f:
                return pickle.load(f)
        except Exception:
            with contextlib.suppress(OSError):
                pkl.unlink()
            return None

    def put(self, source_path: str, document,
            backend_name: str = "", options_sig: str = "") -> None:
        """Guarda `document` en caché para `source_path`."""
        key = _cache_key(source_path, backend_name, options_sig)
        if key is None:
            return
        pkl = self._path(key)
        try:
            with pkl.open("wb") as f:
                pickle.dump(document, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            logger.warning("OCRResultCache: no se pudo guardar caché: %s", exc)

    def invalidate(self, source_path: str,
                   backend_name: str = "", options_sig: str = "") -> bool:
        """Elimina la entrada de caché. Sin backend/opts borra todas las variantes del archivo."""
        if not backend_name and not options_sig:
            abs_path = os.path.abspath(source_path)
            removed = False
            for pkl in list(self._cache_dir.glob("*.pkl")):
                try:
                    with pkl.open("rb") as f:
                        doc = pickle.load(f)
                    if os.path.abspath(getattr(doc, "source_path", "")) == abs_path:
                        pkl.unlink()
                        removed = True
                except Exception:
                    pass
            return removed
        key = _cache_key(source_path, backend_name, options_sig)
        if key is None:
            return False
        pkl = self._path(key)
        if pkl.exists():
            try:
                pkl.unlink()
                return True
            except OSError:
                pass
        return False

    def clear(self) -> int:
        """Elimina todos los archivos de caché. Devuelve cuántos se borraron."""
        removed = 0
        for pkl in self._cache_dir.glob("*.pkl"):
            try:
                pkl.unlink()
                removed += 1
            except OSError:
                pass
        logger.info("OCRResultCache: vaciado (%d entradas)", removed)
        return removed

    def cache_size_bytes(self) -> int:
        total = 0
        for pkl in self._cache_dir.glob("*.pkl"):
            with contextlib.suppress(OSError):
                total += pkl.stat().st_size
        return total

    def cache_size_mb(self) -> float:
        return self.cache_size_bytes() / (1024 * 1024)
