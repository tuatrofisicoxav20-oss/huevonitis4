"""Mide una imagen real con ambas estrategias e imprime JSON listo
para pegar en tests/fixtures/handwriting/expectations.json.

Uso:
    python tools/measure_fixture.py tests/fixtures/handwriting/01_xxx.jpg
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _craft_available() -> bool:
    try:
        from core.inkcore import glyph_detectors
        return bool(glyph_detectors.get_available().get("craft"))
    except Exception:
        return False


def measure(image_path: str) -> dict:
    from core.inkcore.extraction_pipeline import PipelineConfig
    from core.inkcore.extractor import ExtractionOptions
    from core.inkcore.pipeline import InkCorePipeline

    pipeline = InkCorePipeline()

    # Legacy
    t0 = time.perf_counter()
    legacy_glyphs = pipeline.extract(
        image_path, "", ExtractionOptions(use_pipeline=False)
    )
    legacy_time = time.perf_counter() - t0

    # Ensemble (sin labelers para no requerir TrOCR en CI)
    dets = ["classic_cv"]
    if _craft_available():
        dets.append("craft")
    cfg = PipelineConfig(detectors=dets, labelers=[], detector_fusion="union")
    t0 = time.perf_counter()
    ensemble_glyphs = pipeline.extract(
        image_path, "", ExtractionOptions(use_pipeline=True, pipeline_config=cfg)
    )
    ensemble_time = time.perf_counter() - t0

    gold_leg = sum(1 for g in legacy_glyphs if g.tier == "Gold")
    gold_ens = sum(1 for g in ensemble_glyphs if g.tier == "Gold")
    n_leg = max(1, len(legacy_glyphs))
    n_ens = max(1, len(ensemble_glyphs))

    return {
        "legacy": {
            "glyphs": len(legacy_glyphs),
            "gold": gold_leg,
            "gold_ratio": round(gold_leg / n_leg, 3),
            "seconds": round(legacy_time, 2),
        },
        "ensemble": {
            "glyphs": len(ensemble_glyphs),
            "gold": gold_ens,
            "gold_ratio": round(gold_ens / n_ens, 3),
            "seconds": round(ensemble_time, 2),
        },
    }


def suggest_expectations(result: dict) -> dict:
    leg = result["legacy"]
    ens = result["ensemble"]
    min_gold_ratio = min(leg["gold_ratio"], ens["gold_ratio"])
    return {
        "expected_min_glyphs_legacy": int(leg["glyphs"] * 0.85),
        "expected_min_glyphs_ensemble": int(ens["glyphs"] * 0.85),
        "expected_max_seconds_legacy": int(leg["seconds"] * 1.5) + 5,
        "expected_max_seconds_ensemble": int(ens["seconds"] * 1.5) + 10,
        "expected_min_gold_ratio": round(min_gold_ratio * 0.85, 2),
        "notes": "EDITAR: descripción humana del fixture",
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python tools/measure_fixture.py <ruta_imagen>")
        sys.exit(1)

    img_path = sys.argv[1]
    if not Path(img_path).exists():
        print(f"Error: no existe '{img_path}'")
        sys.exit(1)

    print(f"\nMidiendo {Path(img_path).name}…\n")
    result = measure(img_path)
    print("Resultados:")
    print(json.dumps(result, indent=2))
    print("\n--- Sugerencia para expectations.json (margen 85%) ---")
    print(json.dumps(suggest_expectations(result), indent=2))
    print(f"\nClave en expectations.json: \"{Path(img_path).name}\"")
