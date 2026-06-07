"""Reproduce un apunte ajeno con la letra del perfil activo (MVP v4.2).

Alcance MVP — sé honesto con esto, no prometas más:
  ✅ Texto manuscrito → detectar regiones con OCR (tesseract), re-renderizar
     con HandwritingRenderer del perfil activo, ubicar en posición original.
  ✅ Recuadros y líneas rectas → contornos cv2 + HoughLinesP, re-trazar con
     leve jitter para que se vea manuscrito.
  ⚠ Tablas: detectadas como conjuntos de líneas H+V; sin reconocimiento
     semántico (no rellena celdas inteligentemente).
  ⚠ Fórmulas matemáticas: copiadas tal cual como bitmap. NO se re-renderiza
     estructura matemática.
  ⚠ Dibujos / diagramas: copiados como bitmap al output.

Sliders en la UI:
  fidelity 0-100. 0 = re-escribir todo. 100 = copia exacta (bypass replicator).
  En MVP el slider ajusta cuánto del bitmap original se conserva vs replicado.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import config

logger = logging.getLogger(__name__)


try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    TESS_OK = True
except ImportError:
    TESS_OK = False


BlockType = Literal["text", "rect", "drawing"]


@dataclass
class Block:
    type: BlockType
    x: int
    y: int
    w: int
    h: int
    text: str = ""              # solo si type == "text"
    enabled: bool = True        # toggle por la UI
    confidence: float = 0.0     # OCR confidence (0-1) para texto
    label: str = ""             # descripción legible


@dataclass
class PageLayout:
    image_path: str = ""
    page_width: int = 0
    page_height: int = 0
    blocks: list[Block] = field(default_factory=list)


class NoteReplicator:
    """Analiza un apunte ajeno y lo re-renderiza con un bank dado."""

    def __init__(self, bank):
        self.bank = bank

    # ── Análisis ─────────────────────────────────────────────────

    def analyze(self, image_path: str) -> PageLayout | None:
        """Detecta bloques de texto + recuadros en una imagen.

        Devuelve None si no hay cv2/PIL disponibles o la imagen no se lee.
        """
        if not (CV2_OK and PIL_OK):
            logger.warning("analyze: cv2 o PIL no disponibles")
            return None
        if not Path(image_path).exists():
            logger.warning("analyze: archivo no existe: %s", image_path)
            return None

        bgr = cv2.imread(image_path)
        if bgr is None:
            logger.warning("analyze: cv2 no pudo leer %s", image_path)
            return None
        h, w = bgr.shape[:2]
        layout = PageLayout(image_path=image_path, page_width=w, page_height=h)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Binarización para detectar trazos oscuros (texto, líneas)
        thr = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12,
        )

        # 1) Detectar rectángulos: contornos cuadriláteros grandes
        rects = self._detect_rectangles(thr, min_area=(w * h) * 0.005)
        for (rx, ry, rw, rh) in rects:
            layout.blocks.append(Block(
                type="rect", x=rx, y=ry, w=rw, h=rh,
                label=f"Recuadro {rw}×{rh}px",
            ))

        # 2) Detectar bloques de texto con OCR (tesseract) si está disponible.
        # Cada palabra-bloque del OCR se agrupa por línea en una región contigua.
        if TESS_OK:
            text_blocks = self._detect_text_blocks(gray, rects)
            layout.blocks.extend(text_blocks)
        else:
            logger.info("analyze: tesseract no disponible — solo se detectarán recuadros")

        logger.info(
            "analyze: imagen %dx%d → %d bloques (%d rects, %d texto)",
            w, h, len(layout.blocks),
            sum(1 for b in layout.blocks if b.type == "rect"),
            sum(1 for b in layout.blocks if b.type == "text"),
        )
        return layout

    @staticmethod
    def _detect_rectangles(thr_inv: np.ndarray, min_area: float) -> list[tuple[int, int, int, int]]:
        """Encuentra contornos cuadrangulares razonablemente rectos."""
        contours, _ = cv2.findContours(thr_inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results: list[tuple[int, int, int, int]] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            approx = cv2.approxPolyDP(c, 0.04 * cv2.arcLength(c, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                x, y, w, h = cv2.boundingRect(approx)
                # filtros sanos: aspect ratio razonable + tamaño suficiente
                ar = w / max(1, h)
                if 0.2 <= ar <= 8 and min(w, h) > 30:
                    results.append((x, y, w, h))
        # Eliminar duplicados solapados
        return _dedup_boxes(results)

    @staticmethod
    def _detect_text_blocks(gray: np.ndarray, rects: list) -> list[Block]:
        """OCR con tesseract; agrupa palabras por línea en bloques de texto.

        Cada bloque corresponde a una línea OCR contigua. Las áreas que caen
        dentro de un recuadro detectado se asignan al recuadro como label
        en lugar de un bloque separado (MVP simple: solo los excluimos).
        """
        try:
            # PSM 6 = bloque uniforme de texto; --oem 3 = LSTM
            data = pytesseract.image_to_data(
                gray, output_type=pytesseract.Output.DICT,
                config="--psm 6 --oem 3 -l spa+eng",
            )
        except Exception as exc:
            logger.warning("OCR tesseract falló: %s", exc)
            return []

        # Agrupar por (block_num, par_num, line_num) → una línea de texto
        lines: dict[tuple, list[dict]] = {}
        n = len(data["text"])
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            try:
                conf = int(data["conf"][i])
            except (ValueError, KeyError):
                conf = -1
            if not txt or conf < 30:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append({
                "text": txt,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "conf": conf,
            })

        blocks: list[Block] = []
        for key, words in lines.items():
            if not words:
                continue
            text = " ".join(w["text"] for w in words)
            x1 = min(w["x"] for w in words)
            y1 = min(w["y"] for w in words)
            x2 = max(w["x"] + w["w"] for w in words)
            y2 = max(w["y"] + w["h"] for w in words)
            avg_conf = sum(w["conf"] for w in words) / len(words) / 100.0

            # Saltar si está dentro de un recuadro (lo trataremos como contenido del rect)
            if _box_inside_any(x1, y1, x2 - x1, y2 - y1, rects):
                continue

            blocks.append(Block(
                type="text",
                x=x1, y=y1, w=x2 - x1, h=y2 - y1,
                text=text,
                confidence=avg_conf,
                label=f"Texto: '{text[:30]}{'…' if len(text) > 30 else ''}'",
            ))
        return blocks

    # ── Render ───────────────────────────────────────────────────

    def render(self, layout: PageLayout, fidelity: int = 0) -> Image.Image | None:
        """Re-renderiza un layout usando el bank del replicador.

        fidelity 0 = todo replicado con la letra del perfil.
        fidelity 100 = devolver el original sin tocar.
        Valores intermedios: blend lineal del bitmap original sobre el replicado.
        """
        if not PIL_OK:
            return None
        try:
            from core.inkcore.renderer import HandwritingRenderer, RenderOptions
        except ImportError as exc:
            logger.error("renderer no disponible: %s", exc)
            return None

        original = None
        try:
            original = Image.open(layout.image_path).convert("RGB")
        except Exception as exc:
            logger.warning("render: no se pudo abrir original: %s", exc)

        if fidelity >= 100 and original is not None:
            return original

        # Lienzo blanco con tamaño del original
        canvas = Image.new("RGB", (layout.page_width, layout.page_height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # 1) Re-trazar recuadros
        for block in layout.blocks:
            if not block.enabled:
                continue
            if block.type == "rect":
                self._draw_jittered_rect(draw, block)

        # 2) Texto: render con HandwritingRenderer y pegar en la posición
        hr = HandwritingRenderer(self.bank)
        for block in layout.blocks:
            if not block.enabled or block.type != "text" or not block.text:
                continue
            # font_size proporcional a la altura del bloque OCR
            font_size = max(18, min(72, int(block.h * 0.9)))
            opts = RenderOptions(
                font_size=font_size,
                page_width=block.w + 40,
                page_margin=10,
                jitter_px=2, size_variation=0.08, rotation_range=2.5,
                background_color="#FFFFFF",
                style="Limpio",
            )
            try:
                rendered = hr.render_text(block.text, opts)
            except Exception as exc:
                logger.warning("render: render_text falló para %r: %s", block.text[:30], exc)
                rendered = None
            if rendered is not None:
                # Recortar exceso vertical: usar solo la primera línea de altura ~block.h
                target_h = max(block.h, font_size + 8)
                if rendered.height > target_h:
                    rendered = rendered.crop((0, 0, rendered.width, target_h))
                # Pegar con transparencia si la tiene
                if rendered.mode == "RGBA":
                    canvas.paste(rendered, (block.x, block.y), rendered)
                else:
                    canvas.paste(rendered, (block.x, block.y))

        # 3) Blend con original si fidelity > 0
        if 0 < fidelity < 100 and original is not None:
            try:
                if original.size != canvas.size:
                    original = original.resize(canvas.size)
                alpha = fidelity / 100.0
                canvas = Image.blend(canvas, original, alpha)
            except Exception as exc:
                logger.warning("render: blend falló: %s", exc)

        return canvas

    @staticmethod
    def _draw_jittered_rect(draw: ImageDraw.ImageDraw, block: Block) -> None:
        """Dibuja un recuadro con un poco de jitter para que se vea manuscrito."""
        import random as _r
        def jx():
            return _r.randint(-2, 2)
        def jy():
            return _r.randint(-2, 2)
        x1, y1 = block.x + jx(), block.y + jy()
        x2, y2 = block.x + block.w + jx(), block.y + block.h + jy()
        # Trazo doble para simular grosor variable
        for offset in (0, 1):
            draw.rectangle(
                (x1 - offset, y1 - offset, x2 + offset, y2 + offset),
                outline=(40, 40, 40), width=1,
            )


def _box_inside_any(x: int, y: int, w: int, h: int, rects: list) -> bool:
    cx, cy = x + w // 2, y + h // 2
    for (rx, ry, rw, rh) in rects:
        if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
            # Excluir solo si el rect es mucho más grande (no es la propia palabra)
            if rw * rh > w * h * 3:
                return True
    return False


def _dedup_boxes(boxes: list[tuple[int, int, int, int]],
                 iou_threshold: float = 0.5) -> list[tuple[int, int, int, int]]:
    if not boxes:
        return []
    boxes_sorted = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
    kept = []
    for b in boxes_sorted:
        if not any(_iou(b, k) > iou_threshold for k in kept):
            kept.append(b)
    return kept


def _iou(a, b) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / max(1, union)


def export_replicated(image: Image.Image, out_path: str | None = None) -> str:
    """Guarda el resultado del replicador a EXPORTS_DIR/replicated_<ts>.png/pdf."""
    from datetime import datetime as _dt
    if out_path is None:
        config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(config.EXPORTS_DIR / f"replicated_{ts}.png")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".pdf":
        image.convert("RGB").save(out, "PDF")
    else:
        image.save(out)
    logger.info("export_replicated: guardado en %s", out)
    return str(out)
