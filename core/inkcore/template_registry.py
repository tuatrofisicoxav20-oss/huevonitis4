"""Registro persistido de las plantillas que GENERA el usuario.

Problema que resuelve: la UI permite armar plantillas MIXTAS (cualquier combo de
minúsculas + MAYÚSCULAS + dígitos + puntuación + acentuadas + pares) con su
propia geometría. El orquestador de extracción (`extract_pdf_pages`) identifica
cada página comparándola contra un conjunto de presets conocidos
(`TEMPLATE_PRESETS`). Una plantilla mixta NO está entre esos presets, así que el
auto-detect no la reconoce y la página termina `suspect`.

La solución (sin inventar un camino de confianza paralelo): cuando el usuario
genera una plantilla, se REGISTRA su layout acá; al cargar la foto, esos layouts
se inyectan como presets candidatos extra (`presets=`), y la máquina de
detección ya calibrada (agreement CNN para a-z, geometría para non-az) elige el
correcto por página. Validado empíricamente: una hoja mixta rellena puntúa
agreement ~0.64 contra su propio layout vs ~0.04 contra `minusculas_x1` (la
geometría equivocada desalinea la proyección) → la separación es de ~13×.

El registro DEBE persistir en disco: imprimir → escribir → fotografiar cruza
sesiones y reinicios de la app (días). Un snapshot en memoria no alcanza porque
la foto se carga en otra sesión. Tampoco sirve un sidecar junto al PDF: la foto
escaneada es un archivo nuevo sin sidecar. Por eso se guarda un JSON junto al
banco (`TIPOGRAFIA_DIR/_user_templates.json`).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

import config
from core.inkcore.template_sheet import TemplateLayout

logger = logging.getLogger(__name__)

# Tope de layouts recordados: cada uno agrega una pasada de agreement por página
# al cargar una foto, así que no conviene acumular sin límite. Se conservan los
# más recientes (FIFO por orden de registro).
MAX_USER_LAYOUTS = 24


def _registry_path() -> Path:
    return config.TIPOGRAFIA_DIR / "_user_templates.json"


def _charset_str(charset: str | list[str]) -> str:
    """Serializa el charset (str o lista de tokens) a una cadena estable."""
    if isinstance(charset, str):
        return charset
    return "\x1f".join(charset)   # separador de unidad: ningún token lo contiene


def _charset_from_str(s: str, *, is_list: bool) -> str | list[str]:
    return s.split("\x1f") if is_list else s


def layout_key(layout: TemplateLayout) -> str:
    """Nombre estable y único para un layout, derivado de (charset, repeats).

    Dos plantillas con el mismo charset y repeticiones comparten clave (es la
    MISMA plantilla), así el registro deduplica solo.
    """
    raw = f"{_charset_str(layout.charset)}\x00{layout.repeats}"
    return "user_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _layout_to_record(layout: TemplateLayout) -> dict:
    return {
        "key": layout_key(layout),
        "charset": _charset_str(layout.charset),
        "is_list": not isinstance(layout.charset, str),
        "repeats": int(layout.repeats),
        "cols": int(layout.cols),
        "rows": int(layout.rows),
    }


def _record_to_layout(rec: dict) -> TemplateLayout | None:
    try:
        charset = _charset_from_str(rec["charset"], is_list=bool(rec.get("is_list")))
        return TemplateLayout(charset=charset, repeats=int(rec.get("repeats", 1)))
    except Exception as exc:
        logger.warning("template_registry: registro inválido %r (%s)", rec, exc)
        return None


def _read_records() -> list[dict]:
    p = _registry_path()
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict) and r.get("charset")]
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("template_registry: no se pudo leer %s (%s)", p, exc)
    return []


def _atomic_write(records: list[dict]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def register_layouts(layouts: list[TemplateLayout]) -> int:
    """Registra (persistiendo) los layouts de una plantilla recién generada.

    Deduplica por `layout_key`: regenerar la misma plantilla no acumula. Mantiene
    a lo sumo `MAX_USER_LAYOUTS` (los más recientes). Devuelve cuántos layouts
    nuevos se agregaron. Falla silenciosa (loguea) si el disco no responde: no
    debe romper la generación de la plantilla.
    """
    if not layouts:
        return 0
    try:
        records = _read_records()
        by_key = {r["key"]: r for r in records if "key" in r}
        order = [r["key"] for r in records if "key" in r]
        added = 0
        for lay in layouts:
            rec = _layout_to_record(lay)
            if rec["key"] not in by_key:
                added += 1
                order.append(rec["key"])
            else:
                # Re-registrar lo "refresca" al frente del FIFO.
                order = [k for k in order if k != rec["key"]] + [rec["key"]]
            by_key[rec["key"]] = rec
        # Conservar sólo los MAX_USER_LAYOUTS más recientes.
        keep = order[-MAX_USER_LAYOUTS:]
        new_records = [by_key[k] for k in keep]
        _atomic_write(new_records)
        if added:
            logger.info("template_registry: +%d layout(s) de usuario (total %d)",
                        added, len(new_records))
        return added
    except Exception as exc:
        logger.warning("template_registry: no se pudo registrar (%s)", exc)
        return 0


def load_user_presets() -> dict[str, TemplateLayout]:
    """Layouts de usuario persistidos como dict {nombre: TemplateLayout}.

    Pensado para fusionarse con `TEMPLATE_PRESETS` e inyectarse por `presets=` en
    `extract_pdf_pages`. Devuelve {} si no hay registro o PIL/registro falla.
    """
    out: dict[str, TemplateLayout] = {}
    for rec in _read_records():
        lay = _record_to_layout(rec)
        if lay is not None:
            out[rec.get("key") or layout_key(lay)] = lay
    return out


def augmented_presets() -> dict[str, TemplateLayout]:
    """`TEMPLATE_PRESETS` + los layouts de usuario (estos no pisan los fijos)."""
    from core.inkcore.template_sheet import TEMPLATE_PRESETS
    merged: dict[str, TemplateLayout] = dict(load_user_presets())
    merged.update(TEMPLATE_PRESETS)   # los fijos tienen prioridad de nombre
    return merged
