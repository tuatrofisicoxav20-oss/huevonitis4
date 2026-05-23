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
    _model_lock = threading.Lock()

    @classmethod
    def get(cls, key: str, loader: Callable[[], Any]) -> Any:
        """Devuelve el modelo `key`, cargándolo con `loader` si no existe."""
        if key in cls._models:
            return cls._models[key]
        with cls._model_lock:
            if key not in cls._models:
                logger.info("ModelCache: cargando '%s'…", key)
                cls._models[key] = loader()
                logger.info("ModelCache: '%s' cargado", key)
            return cls._models[key]

    @classmethod
    def peek(cls, key: str) -> Any | None:
        """Devuelve el modelo si ya está cargado, sin cargar nada."""
        return cls._models.get(key)

    @classmethod
    def evict(cls, key: str) -> bool:
        """Elimina un modelo del caché. Devuelve True si existía."""
        with cls._model_lock:
            if key in cls._models:
                del cls._models[key]
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
        with cls._model_lock:
            keys = list(cls._models.keys())
            cls._models.clear()
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
