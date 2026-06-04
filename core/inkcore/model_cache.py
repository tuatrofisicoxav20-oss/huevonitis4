"""
ModelCache — caché global de modelos de IA en memoria.

Patrón double-checked locking para carga lazy y thread-safe.
Todos los backends opcionales (TrOCR, CRAFT, docTR, EasyOCR…) usan esta
clase para evitar múltiples cargas del mismo modelo si distintas partes
de la app lo piden al mismo tiempo.
"""
import gc
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ModelCache:
    """Caché global de modelos pesados (singleton de clase, sin instanciar)."""

    _models: dict[str, Any] = {}
    # F9 — locking POR CLAVE. El lock global anterior congelaba la app durante la
    # primera carga de TrOCR (~400MB): cualquier hilo que pidiera CUALQUIER otro
    # modelo (p.ej. Tesseract) quedaba bloqueado, anulando el diseño de extraer en
    # hilo de fondo. Ahora cada key tiene su propio lock, así cargar TrOCR no
    # bloquea a quien pide otro modelo. `_registry_lock` solo protege la creación
    # de los locks por clave y las mutaciones estructurales de _models (evict/clear);
    # se toma brevísimamente, nunca durante un loader().
    _locks: dict[str, threading.Lock] = {}
    _registry_lock = threading.Lock()

    @classmethod
    def _lock_for(cls, key: str) -> threading.Lock:
        with cls._registry_lock:
            lk = cls._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                cls._locks[key] = lk
            return lk

    @classmethod
    def get(cls, key: str, loader: Callable[[], Any]) -> Any:
        """Devuelve el modelo `key`, cargándolo con `loader` si no existe.

        El `loader` corre bajo el lock de ESTA clave, no bajo un lock global:
        cargar un modelo lento no bloquea a quien pide otro distinto.
        """
        # Fast path sin lock: si ya está cargado, devolver directo.
        if key in cls._models:
            return cls._models[key]
        lk = cls._lock_for(key)
        with lk:
            # Double-check tras adquirir el lock de la clave.
            if key in cls._models:
                return cls._models[key]
            logger.info("ModelCache: cargando '%s'…", key)
            # Si loader() lanza, NO escribimos en _models: la clave queda ausente
            # (no corrupta) y el `with` libera el lock. El próximo get reintenta.
            model = loader()
            cls._models[key] = model
            logger.info("ModelCache: '%s' cargado", key)
            return model

    @classmethod
    def peek(cls, key: str) -> Any | None:
        """Devuelve el modelo si ya está cargado, sin cargar nada."""
        return cls._models.get(key)

    @classmethod
    def evict(cls, key: str) -> bool:
        """Elimina un modelo del caché. Devuelve True si existía."""
        with cls._registry_lock:
            if key in cls._models:
                del cls._models[key]
                cls._locks.pop(key, None)
                logger.info("ModelCache: '%s' eliminado", key)
            else:
                return False
        # Liberar fuera del lock
        gc.collect()
        _try_free_cuda()
        return True

    @classmethod
    def clear(cls) -> None:
        """Vacía todo el caché (libera memoria de todos los modelos)."""
        with cls._registry_lock:
            keys = list(cls._models.keys())
            cls._models.clear()
            cls._locks.clear()
        # Liberar fuera del lock
        gc.collect()
        _try_free_cuda()
        if keys:
            logger.info("ModelCache: vaciado (%s modelos)", len(keys))

    @classmethod
    def loaded_keys(cls) -> list[str]:
        """Lista de claves actualmente cargadas."""
        return list(cls._models.keys())

    @classmethod
    def memory_info(cls) -> dict[str, Any]:
        """Info resumida: cuántos modelos hay cargados y sus claves."""
        return {"count": len(cls._models), "keys": cls.loaded_keys()}


def _try_free_cuda() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("ModelCache: torch.cuda.empty_cache fallo: %s", exc)
