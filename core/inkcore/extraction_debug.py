"""
Generación del overlay de debug del pipeline ensemble de extracción.
Separado de extraction_pipeline.py para mantener los módulos por debajo de
~420 líneas. extraction_pipeline lo re-importa y lo usa cuando
PipelineConfig.debug_overlay=True.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import config as _config

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


def _generate_debug_overlay(
    img_bgr: np.ndarray,
    accepted: list[tuple],
    discarded: list[tuple],
) -> str | None:
    """Genera PNG con overlay de cajas aceptadas y descartadas."""
    try:
        import cv2
    except ImportError:
        return None

    overlay = img_bgr.copy()
    _h, w = overlay.shape[:2]

    for fb, _, char, conf in accepted:
        # Verde si todos lo vieron, amarillo si solo algunos
        if fb.agreement_score >= 0.99:
            color = (0, 200, 0)
        else:
            color = (0, 180, 255)  # BGR amarillo
        cv2.rectangle(overlay, (fb.x, fb.y), (fb.x + fb.w, fb.y + fb.h), color, 2)
        label = char
        if conf is not None:
            label += f" {conf:.2f}"
        cv2.putText(overlay, label, (fb.x, max(10, fb.y - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    for fb, _, _char, _conf in discarded:
        cv2.rectangle(overlay, (fb.x, fb.y), (fb.x + fb.w, fb.y + fb.h),
                      (0, 0, 200), 1)

    # Leyenda en esquina superior derecha
    legend_x = max(0, w - 210)
    cv2.rectangle(overlay, (legend_x, 5), (w - 5, 75), (20, 20, 30), -1)
    cv2.putText(overlay, "Verde: todos detectores", (legend_x + 5, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 200, 0), 1)
    cv2.putText(overlay, "Amarillo: algunos", (legend_x + 5, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 180, 255), 1)
    cv2.putText(overlay, "Rojo: descartados", (legend_x + 5, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 200), 1)

    debug_dir = _config.DEBUG_DIR
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    out_path = str(debug_dir / f"extraction_{ts}.png")
    cv2.imwrite(out_path, overlay)
    logger.info("Debug overlay guardado en %s", out_path)
    return out_path
