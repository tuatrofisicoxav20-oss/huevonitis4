"""
Herramienta de comparación de estrategias de segmentación de caracteres.

Uso:
    python tools/compare_strategies.py <ruta_imagen> [texto_referencia]

Si no se proporciona texto de referencia, se intenta usar Tesseract para
obtener una estimación del texto de la primera línea.
"""
import logging
import os
import sys

# Agregar el directorio raíz de la app al path
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

logging.basicConfig(level=logging.WARNING)  # suprimir logs de producción durante prueba

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    print("ERROR: cv2 no disponible. Instalar con: pip install opencv-python")
    sys.exit(1)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    print("ERROR: Pillow no disponible. Instalar con: pip install Pillow")
    sys.exit(1)

try:
    import pytesseract
    TESS_OK = True
except ImportError:
    TESS_OK = False
    print("ADVERTENCIA: pytesseract no disponible — texto de referencia debe proveerse manualmente")

from core.inkcore.extractor import ExtractionOptions, GlyphExtractor  # noqa: E402


def get_reference_text_from_tesseract(line_mask: np.ndarray) -> str:
    """Intenta extraer texto de la primera línea con Tesseract."""
    if not TESS_OK:
        return ""
    try:
        h, w = line_mask.shape[:2]
        target_h = max(200, h * 3)
        scale = target_h / max(1, h)
        scaled_w = int(w * scale)
        lm = cv2.resize(line_mask, (scaled_w, target_h), interpolation=cv2.INTER_LINEAR)
        _, lm = cv2.threshold(lm, 127, 255, cv2.THRESH_BINARY)
        border = 50
        lm = cv2.copyMakeBorder(lm, border, border, border, border,
                                 cv2.BORDER_CONSTANT, value=0)
        tess_in = 255 - lm
        pil_in = Image.fromarray(tess_in, mode="L")
        text = pytesseract.image_to_string(pil_in, lang="spa",
                                            config="--psm 7 --oem 3").strip()
        return "".join(c for c in text if c not in " \n\t")
    except Exception as e:
        print(f"  Tesseract OCR falló: {e}")
        return ""


def run_comparison(image_path: str, ref_text: str = "") -> None:
    print(f"\n{'='*70}")
    print("  COMPARACIÓN DE ESTRATEGIAS DE SEGMENTACIÓN")
    print(f"  Imagen: {os.path.basename(image_path)}")
    print(f"{'='*70}\n")

    if not os.path.exists(image_path):
        print(f"ERROR: imagen no encontrada: {image_path}")
        return

    extractor = GlyphExtractor()
    opts = ExtractionOptions()

    # Cargar y preprocesar
    print("Cargando y preprocesando imagen...")
    img = cv2.imread(image_path)
    if img is None:
        print("ERROR: no se pudo cargar la imagen")
        return

    img = extractor._apply_manual(img, opts)
    img = extractor._scale(img)
    img = extractor._autocrop(img)
    img, skew = extractor._deskew(img)
    if abs(skew) > 0.3:
        print(f"  Inclinación corregida: {skew:.2f}°")

    gray, raw_mask, clean = extractor._full_preprocess(img, opts)

    # Detectar líneas
    print("Detectando líneas de texto...")
    line_boxes = extractor._find_line_boxes(clean)
    if not line_boxes:
        print("ERROR: no se detectaron líneas de texto")
        return

    print(f"  {len(line_boxes)} línea(s) detectada(s)")
    for i, lb in enumerate(line_boxes):
        print(f"    Línea {i}: x={lb.x} y={lb.y} w={lb.w} h={lb.h}")

    # Usar la primera línea
    lb = line_boxes[0]
    lx, ly = lb.x, lb.y
    line_mask = clean[ly:ly + lb.h, lx:lx + lb.w]

    if line_mask.size == 0 or not np.any(line_mask > 0):
        print("ERROR: máscara de la primera línea vacía")
        return

    # Texto de referencia
    if not ref_text:
        print("\nObteniendo texto de referencia con Tesseract...")
        ref_text = get_reference_text_from_tesseract(line_mask)
        if ref_text:
            print(f"  Tesseract detectó: '{ref_text}'")
        else:
            # Fallback: estimar número de chars por ancho de banda
            char_w_estimate = max(10, lb.h)
            n_estimate = max(1, int(lb.w / char_w_estimate))
            ref_text = "a" * n_estimate
            print(f"  Sin OCR — usando {n_estimate} caracteres de relleno ('a'×{n_estimate})")

    chars = [c for c in ref_text if c != " "]
    if not chars:
        print("ERROR: texto de referencia vacío o solo espacios")
        return

    n = len(chars)
    print(f"\nTexto de referencia: '{ref_text}' ({n} caracteres)")

    # Calcular x_min / x_max de la banda
    vpp = np.sum(line_mask > 0, axis=0).astype(np.float32)
    ink_cols = np.where(vpp > 0)[0]
    if len(ink_cols) == 0:
        print("ERROR: banda sin tinta")
        return
    p2 = max(0, int(len(ink_cols) * 0.02))
    p98 = min(len(ink_cols) - 1, int(len(ink_cols) * 0.98))
    x_min = int(ink_cols[p2])
    x_max = int(ink_cols[p98]) + 1

    print(f"  Span tinta: x={x_min}..{x_max} ({x_max - x_min}px)")
    print(f"  Ancho promedio por char: {(x_max - x_min) / n:.1f}px")

    # Ejecutar comparación
    print("\nEjecutando todas las estrategias...")
    results = extractor._test_all_strategies(
        band_img=line_mask,
        band_binary=line_mask,
        x_min=x_min,
        x_max=x_max,
        n=n,
        chars=chars,
        line_mask=line_mask,
    )

    if not results:
        print("ERROR: _test_all_strategies devolvió resultado vacío")
        return

    # Imprimir tabla de resultados
    print(f"\n{'─'*70}")
    print(f"{'Estrategia':<38} {'Glifos':>6} {'Avg Q':>7} {'Min Q':>7} {'Max Q':>7}")
    print(f"{'─'*70}")

    best_name = ""
    best_score = -1.0

    for name, r in results.items():
        if "error" in r:
            print(f"{name:<38} {'ERROR':>6}  {r['error'][:28]}")
            continue
        gc = r.get("glyph_count", 0)
        avg = r.get("avg_quality", 0.0)
        mn = r.get("min_quality", 0.0)
        mx = r.get("max_quality", 0.0)
        note = r.get("note", "")
        if note:
            print(f"{name:<38} {note:>28}")
            continue
        # Puntuación combinada: priorizar glifos completos + calidad promedio
        combined = avg * 0.7 + (gc / max(1, n)) * 0.3
        if combined > best_score:
            best_score = combined
            best_name = name
        print(f"{name:<38} {gc:>6}  {avg:>7.3f}  {mn:>7.3f}  {mx:>7.3f}")

    print(f"{'─'*70}")
    print(f"\nMejor estrategia: [{best_name}]  (score combinado: {best_score:.3f})")

    # Detalle de fronteras de la mejor estrategia
    if best_name in results and "boundaries" in results[best_name]:
        bounds = results[best_name]["boundaries"]
        print(f"  Fronteras: {bounds[:10]}{'...' if len(bounds) > 10 else ''}")

    print(f"\n{'='*70}\n")


def run_ocr_comparison(image_path: str) -> None:
    """Compara todos los backends OCR disponibles sobre la misma imagen."""
    import time

    print(f"\n{'='*70}")
    print("  COMPARACIÓN DE BACKENDS OCR")
    print(f"  Imagen: {os.path.basename(image_path)}")
    print(f"{'='*70}\n")

    if not os.path.exists(image_path):
        print(f"ERROR: imagen no encontrada: {image_path}")
        return

    try:
        from core.ocr import backends as _backends
    except ImportError as e:
        print(f"ERROR: no se puede importar backends OCR: {e}")
        return

    available = _backends.get_available()
    print(f"Backends registrados: {list(available.keys())}")
    print(f"Disponibles: {[k for k, v in available.items() if v]}\n")

    results = {}
    for name, is_avail in available.items():
        if not is_avail:
            results[name] = {"status": "no instalado", "text": "", "time_ms": 0}
            continue
        print(f"Probando {name}...")
        try:
            backend = _backends.get_backend(name)
            t0 = time.perf_counter()
            text = backend.extract_text(image_path)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            word_count = len(text.split()) if text else 0
            results[name] = {
                "status": "ok",
                "text": text[:200] + ("…" if len(text) > 200 else ""),
                "time_ms": elapsed_ms,
                "word_count": word_count,
            }
            print(f"  {elapsed_ms:.0f} ms | {word_count} palabras")
        except Exception as exc:
            results[name] = {"status": f"error: {exc}", "text": "", "time_ms": 0}
            print(f"  ERROR: {exc}")

    print(f"\n{'─'*70}")
    print(f"{'Backend':<16} {'Estado':>12} {'ms':>8} {'Palabras':>10}")
    print(f"{'─'*70}")
    for name, r in results.items():
        status = r.get("status", "?")
        t = r.get("time_ms", 0)
        w = r.get("word_count", "-")
        print(f"{name:<16} {status:>12} {t:>8.0f} {str(w):>10}")
    print(f"{'─'*70}\n")

    for name, r in results.items():
        if r.get("status") == "ok" and r.get("text"):
            print(f"[{name}] primeras líneas:")
            for line in r["text"].split("\n")[:5]:
                if line.strip():
                    print(f"  {line}")
            print()


def run_ensemble_comparison(
    image_path: str,
    strategies: list[str],
    labelers: list[str],
    output_html: str | None,
) -> None:
    """Compara estrategias del pipeline ensemble y genera informe HTML opcional."""
    import time

    print(f"\n{'='*70}")
    print("  COMPARACIÓN DE ESTRATEGIAS ENSEMBLE")
    print(f"  Imagen: {os.path.basename(image_path)}")
    print(f"  Estrategias: {strategies}")
    print(f"  Labelers:    {labelers}")
    print(f"{'='*70}\n")

    if not os.path.exists(image_path):
        print(f"ERROR: imagen no encontrada: {image_path}")
        return

    try:
        from core.inkcore.extraction_pipeline import (
            GlyphExtractionPipeline, PipelineConfig,
        )
    except ImportError as exc:
        print(f"ERROR: {exc}")
        return

    _STRATEGY_CONFIGS = {
        "legacy": None,  # usa flujo extractor legacy
        "classic_only": PipelineConfig(detectors=["classic_cv"], labelers=labelers,
                                       debug_overlay=False),
        "craft_only": PipelineConfig(detectors=["craft"], labelers=labelers,
                                     debug_overlay=False),
        "paddle_only": PipelineConfig(detectors=["paddle_det"], labelers=labelers,
                                      debug_overlay=False),
        "ensemble_all": PipelineConfig(detectors=["classic_cv", "craft", "paddle_det"],
                                       detector_fusion="union", labelers=labelers,
                                       debug_overlay=True),
        "union": PipelineConfig(detectors=["classic_cv", "craft"],
                                detector_fusion="union", labelers=labelers),
        "intersection": PipelineConfig(detectors=["classic_cv", "craft"],
                                       detector_fusion="intersection", labelers=labelers),
        "cascade": PipelineConfig(detectors=["classic_cv", "craft"],
                                  detector_fusion="cascade", labelers=labelers),
    }

    results_by_strategy = {}
    overlay_paths = {}

    for strat_name in strategies:
        cfg = _STRATEGY_CONFIGS.get(strat_name)
        print(f"Ejecutando '{strat_name}'...")
        t0 = time.perf_counter()
        try:
            if strat_name == "legacy" or cfg is None:
                from core.inkcore.extractor import GlyphExtractor, ExtractionOptions
                ext = GlyphExtractor()
                glyphs = ext.extract_from_image(
                    image_path, "", ExtractionOptions(use_pipeline=False)
                )
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                results_by_strategy[strat_name] = {
                    "glyphs": glyphs,
                    "time_ms": elapsed_ms,
                    "stats": {"fused_count": len(glyphs)},
                    "timings": {"total_ms": elapsed_ms},
                }
            else:
                cfg.debug_overlay = output_html is not None
                pipeline = GlyphExtractionPipeline(cfg)
                result = pipeline.extract(image_path)
                elapsed_ms = result.timings_ms.get("total_ms", 0)
                results_by_strategy[strat_name] = {
                    "glyphs": result.glyphs,
                    "time_ms": elapsed_ms,
                    "stats": result.stats,
                    "timings": result.timings_ms,
                }
                if result.debug_image_path:
                    overlay_paths[strat_name] = result.debug_image_path
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results_by_strategy[strat_name] = {
                "glyphs": [], "time_ms": 0, "stats": {"error": str(exc)},
                "timings": {},
            }

    # Imprimir tabla
    print(f"\n{'─'*70}")
    print(f"{'Estrategia':<22} {'Glifos':>7} {'AvgQ':>7} {'Time(ms)':>9}")
    print(f"{'─'*70}")
    for name, r in results_by_strategy.items():
        glyphs = r["glyphs"]
        avg_q = (sum(g.quality_score for g in glyphs) / len(glyphs)
                 if glyphs else 0.0)
        print(f"{name:<22} {len(glyphs):>7}  {avg_q:>6.3f}  {r['time_ms']:>8}")
    print(f"{'─'*70}\n")

    if output_html:
        _write_html_report(image_path, results_by_strategy, overlay_paths, output_html)
        print(f"Informe HTML guardado en: {output_html}")


def _write_html_report(image_path: str, results: dict, overlays: dict, out: str) -> None:
    import base64
    from pathlib import Path

    def img_to_b64(path: str) -> str:
        try:
            return base64.b64encode(Path(path).read_bytes()).decode()
        except Exception:
            return ""

    orig_b64 = img_to_b64(image_path)
    ext_lower = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext_lower, "png")

    rows_html = ""
    for strat, r in results.items():
        glyphs = r["glyphs"]
        avg_q = (sum(g.quality_score for g in glyphs) / len(glyphs)
                 if glyphs else 0.0)
        overlay_html = ""
        if strat in overlays:
            ov_b64 = img_to_b64(overlays[strat])
            if ov_b64:
                overlay_html = (
                    f'<img src="data:image/png;base64,{ov_b64}" '
                    f'style="max-width:300px;border:1px solid #444">'
                )
        chars_found = ", ".join(
            f"{g.char}({g.quality_score:.2f})" for g in glyphs[:20]
        )
        rows_html += f"""
        <tr>
          <td><b>{strat}</b></td>
          <td>{len(glyphs)}</td>
          <td>{avg_q:.3f}</td>
          <td>{r['time_ms']} ms</td>
          <td style="font-size:0.8em">{chars_found}</td>
          <td>{overlay_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Compare Strategies — {Path(image_path).name}</title>
<style>
  body{{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #444;padding:8px 12px;text-align:left}}
  th{{background:#16213e}} tr:nth-child(even){{background:#0f3460}}
  img{{border-radius:4px}}
</style></head>
<body>
<h1>Comparación de estrategias</h1>
<p><b>Imagen:</b> {image_path}</p>
<img src="data:image/{mime};base64,{orig_b64}" style="max-width:600px;margin-bottom:20px">
<table>
  <tr><th>Estrategia</th><th>Glifos</th><th>Avg Q</th><th>Tiempo</th>
      <th>Chars encontrados</th><th>Overlay</th></tr>
  {rows_html}
</table>
</body></html>"""
    Path(out).write_text(html, encoding="utf-8")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Comparación de estrategias de extracción de glifos"
    )
    parser.add_argument("image", help="Ruta a la imagen")
    parser.add_argument("ref_text", nargs="?", default="",
                        help="Texto de referencia (para modo legacy)")
    parser.add_argument("--ocr", action="store_true",
                        help="Comparar backends OCR en vez de estrategias de segmentación")
    parser.add_argument("--strategies",
                        default="legacy,classic_only,ensemble_all",
                        help="Estrategias separadas por coma "
                             "(legacy,classic_only,craft_only,paddle_only,"
                             "ensemble_all,union,intersection,cascade)")
    parser.add_argument("--labelers", default="",
                        help="Labelers separados por coma (tesseract_labeler,trocr_labeler)")
    parser.add_argument("--output", default=None,
                        help="Ruta del informe HTML de salida")

    args = parser.parse_args()

    if args.ocr:
        run_ocr_comparison(args.image)
    elif args.strategies and args.strategies != "segmentation":
        strats = [s.strip() for s in args.strategies.split(",") if s.strip()]
        labelers = [l.strip() for l in args.labelers.split(",") if l.strip()]
        run_ensemble_comparison(args.image, strats, labelers, args.output)
    else:
        run_comparison(args.image, args.ref_text)


if __name__ == "__main__":
    main()
