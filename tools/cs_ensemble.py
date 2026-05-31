"""
Comparación de backends OCR y de estrategias del pipeline ensemble.

Incluye:
  - run_ocr_comparison: compara todos los backends OCR disponibles.
  - run_ensemble_comparison: compara estrategias del pipeline ensemble y
    delega en cs_report para el informe HTML opcional.
"""
import os
import sys

# Agregar el directorio raíz de la app al path
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from tools.cs_report import _write_html_report  # noqa: E402


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
