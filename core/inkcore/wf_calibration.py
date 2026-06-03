"""Salto 4 — Calibración del factor de ancho `wf` a la letra del usuario.

La tabla fija de `extractor_align_basic.wf` (m=1.30, i=0.40…) está pensada para
"español promedio". La letra de cada usuario no es la promedio, y esos anchos
equivocados empujan mal todas las fronteras de carácter.

Aquí acumulamos, a lo largo de las sesiones, el ancho REAL (normalizado a la
altura de línea) de cada carácter CONFIRMADO por verificación cruzada (consenso
de labelers + match con la referencia, la F4). Cuando hay suficientes muestras
para un carácter, `wf()` usa la MEDIANA aprendida en vez de la tabla.

Persistencia: `config.TIPOGRAFIA_DIR / wf_usuario.json` (por perfil, ya que
TIPOGRAFIA_DIR apunta al perfil activo).

Formato:
    {"a": {"samples": [0.81, 0.79, 0.83]}, "m": {"samples": [...]}, ...}
"""
from __future__ import annotations

import json
import logging
import threading

import config

logger = logging.getLogger(__name__)

MIN_SAMPLES = 3        # mínimo de muestras para confiar en el valor aprendido
MAX_SAMPLES = 60       # cap por carácter (ventana deslizante)
WF_FLOOR = 0.20        # piso/techo de cordura para el ancho normalizado
WF_CEIL = 2.20

_lock = threading.RLock()
_cache: dict | None = None
_cache_path = None     # ruta desde la que se cargó el cache (para detectar perfil)


def _path():
    return config.TIPOGRAFIA_DIR / "wf_usuario.json"


def _load() -> dict:
    """Carga (y cachea) el JSON. Recarga si cambió la ruta (cambio de perfil)."""
    global _cache, _cache_path
    p = _path()
    with _lock:
        if _cache is not None and _cache_path == p:
            return _cache
        data: dict = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("wf_calibration: %s ilegible (%s); empezando vacío", p, exc)
                data = {}
        _cache = data
        _cache_path = p
        return _cache


def invalidate() -> None:
    """Olvida el cache en memoria (tests / cambio de perfil)."""
    global _cache, _cache_path
    with _lock:
        _cache = None
        _cache_path = None


def record(char: str, norm_width: float) -> None:
    """Registra una muestra de ancho normalizado (ancho_px / altura_línea_px) de
    un carácter VERIFICADO. No persiste a disco hasta `flush()`."""
    if not char or len(char) != 1:
        return
    if not (WF_FLOOR <= norm_width <= WF_CEIL):
        return  # muestra fuera de rango razonable → ruido de segmentación
    with _lock:
        data = _load()
        entry = data.setdefault(char, {"samples": []})
        samples = entry.setdefault("samples", [])
        samples.append(round(float(norm_width), 4))
        if len(samples) > MAX_SAMPLES:
            del samples[: len(samples) - MAX_SAMPLES]  # ventana deslizante


def flush() -> bool:
    """Persiste el cache a disco. Devuelve True si escribió."""
    with _lock:
        if _cache is None:
            return False
        p = _path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(_cache, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            return True
        except OSError as exc:
            logger.warning("wf_calibration: no se pudo guardar %s: %s", p, exc)
            return False


def record_many(pairs: list[tuple[str, float]]) -> None:
    """Conveniencia: registra varias muestras y persiste una sola vez."""
    if not pairs:
        return
    with _lock:
        for ch, w in pairs:
            record(ch, w)
        flush()


def learned_wf(char: str, min_samples: int = MIN_SAMPLES) -> float | None:
    """Ancho aprendido para `char` (mediana de las muestras) si hay suficientes;
    si no, None (para que el llamador caiga a la tabla fija).

    Usa MEDIANA (no media) para que 1 muestra rara no mande, y exige un piso de
    muestras. El valor se recorta a [WF_FLOOR, WF_CEIL] por cordura.
    """
    if not char:
        return None
    with _lock:
        data = _load()
        entry = data.get(char)
        if not entry:
            return None
        samples = entry.get("samples", [])
        if len(samples) < max(1, min_samples):
            return None
        ordered = sorted(samples)
        n = len(ordered)
        mid = n // 2
        median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
        return float(min(WF_CEIL, max(WF_FLOOR, median)))


def stats() -> dict:
    """Resumen {char: n_muestras} para diagnóstico/UI."""
    with _lock:
        data = _load()
        return {ch: len(e.get("samples", [])) for ch, e in data.items()}
