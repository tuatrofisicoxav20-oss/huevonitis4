"""Estrategias de alineación carácter por carácter.

Cada función recibe el VPP (perfil vertical de tinta) o la máscara binaria
de la línea y devuelve `n+1` posiciones X (incluyen `x_min` y `x_max`).

Estrategias:
  - inkflow     : masa de tinta acumulada calibrada por `wf(char)`
  - vpp_only    : VPP puro con valles por prominencia
  - uniform     : división de ancho igual (línea base)
  - dp_energy   : programación dinámica O(L·k)
  - cc_first    : componentes conectados → grupos
  - hybrid_v2   : inkflow + columna mínima + verificación CC (primario)
  - find_word_gaps : pre-alineación por palabras

NOTA: este módulo conserva la API pública histórica re-exportando las
implementaciones desde sus submódulos por familia:
  - extractor_align_basic    : wf, inkflow, vpp_only, uniform, find_word_gaps
  - extractor_align_advanced : dp_energy, cc_first, hybrid_v2
"""
from __future__ import annotations

from core.inkcore.extractor_align_advanced import (
    align_cc_first,
    align_dp_energy,
    align_hybrid_v2,
)
from core.inkcore.extractor_align_basic import (
    MIN_COMP_AREA,
    align_inkflow,
    align_uniform,
    align_vpp_only,
    find_word_gaps,
    wf,
)

__all__ = [
    "MIN_COMP_AREA",
    "align_cc_first",
    "align_dp_energy",
    "align_hybrid_v2",
    "align_inkflow",
    "align_uniform",
    "align_vpp_only",
    "find_word_gaps",
    "wf",
]
