"""Comparador real-vs-sintético de métricas de realismo (Fase R0).

CLI:  python -m tools.eval_render.compare real.png synth.png [--json salida.json]

Imprime una tabla lado a lado con todas las métricas de metrics.py y un
veredicto por métrica: ✅ si el sintético cae dentro de ±30% del valor real,
❌ si no. Para métricas centradas en cero (slant_mean, baseline_autocorr) el
porcentaje no significa nada cuando el real ≈ 0, así que ahí el veredicto usa
diferencia absoluta con la tolerancia de _ABS_TOL.
"""
from __future__ import annotations

import argparse
import json
import sys

from tools.eval_render.metrics import metrics_from_path

# Tolerancia relativa del veredicto (±30% del real).
REL_TOL = 0.30

# Métricas que pueden valer ~0 legítimamente: el veredicto pasa a |Δ| ≤ tol.
_ABS_TOL: dict[str, float] = {
    "slant_mean": 1.5,          # grados
    "baseline_autocorr": 0.25,  # correlación
}

# Conteos: informativos, sin veredicto (dependen del texto, no del realismo).
_INFO_ONLY = {"n_boxes", "n_lines"}


def _verdict(key: str, real: float, synth: float) -> str:
    if key in _INFO_ONLY:
        return "—"
    abs_tol = _ABS_TOL.get(key)
    if abs_tol is not None and abs(real) < abs_tol:
        return "✅" if abs(synth - real) <= abs_tol else "❌"
    if abs(real) < 1e-9:
        return "✅" if abs(synth) < 1e-9 else "❌"
    return "✅" if abs(synth - real) / abs(real) <= REL_TOL else "❌"


def compare(real_path: str, synth_path: str) -> dict:
    """Métricas de ambas imágenes + veredicto por métrica. JSON-serializable."""
    real = metrics_from_path(real_path)
    synth = metrics_from_path(synth_path)
    rows = {}
    for key in real:
        rows[key] = {
            "real": real[key],
            "synth": synth.get(key, 0.0),
            "verdict": _verdict(key, float(real[key]), float(synth.get(key, 0.0))),
        }
    return rows


def _print_table(rows: dict) -> None:
    name_w = max(len(k) for k in rows) + 2
    print(f"{'métrica':<{name_w}} {'real':>12} {'synth':>12}  veredicto")
    print("-" * (name_w + 38))
    for key, r in rows.items():
        print(f"{key:<{name_w}} {r['real']:>12} {r['synth']:>12}  {r['verdict']}")
    fails = [k for k, r in rows.items() if r["verdict"] == "❌"]
    print("-" * (name_w + 38))
    if fails:
        print(f"❌ {len(fails)} métrica(s) fuera de ±{int(REL_TOL * 100)}%: "
              + ", ".join(fails))
    else:
        print("✅ todas las métricas dentro de tolerancia")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compara métricas de realismo: página real vs render sintético.")
    parser.add_argument("real", help="PNG de la página real escaneada")
    parser.add_argument("synth", help="PNG del render sintético")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="guardar el resultado como JSON en esta ruta")
    args = parser.parse_args(argv)
    rows = compare(args.real, args.synth)
    _print_table(rows)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"JSON → {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
