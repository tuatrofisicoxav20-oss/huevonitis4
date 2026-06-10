"""Calibrador de perfil desde una página manuscrita REAL (Fase R4 — C2/H9).

Los σ del render dejan de ser números mágicos: se MIDEN de una página escrita
por el usuario (la "página patrón", ver tools/eval_render/README.md) y se
guardan en ``tipografia/{profile_id}/calibration.json``. El Writer los usa
por default vía RenderOptions.from_calibration (con clamps de seguridad).

Uso:
    python -m tools.calibrate_profile pagina_real.png
    python -m tools.calibrate_profile pagina_real.png --profile juan
    python -m tools.calibrate_profile pagina_real.png --out otro/lugar.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def calibrate(image_path: str, out_path: "str | Path") -> dict:
    """Mide la página y escribe calibration.json. Devuelve el dict guardado."""
    from tools.eval_render.metrics import metrics_from_path

    metrics = metrics_from_path(image_path)
    data = {
        "version": 1,
        "source_image": str(Path(image_path).name),
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calibra las varianzas del render desde una página real.")
    parser.add_argument("image", help="foto/escaneo de la página patrón")
    parser.add_argument("--profile", default=None,
                        help="perfil destino (default: el perfil default)")
    parser.add_argument("--out", default=None,
                        help="ruta explícita del JSON (ignora --profile)")
    args = parser.parse_args(argv)

    if args.out:
        out = Path(args.out)
    else:
        import config
        pid = args.profile or config.DEFAULT_PROFILE_ID
        out = config.TIPOGRAFIA_DIR / pid / "calibration.json"

    data = calibrate(args.image, out)
    m = data["metrics"]
    print(f"calibration.json → {out}")
    print(f"  letras detectadas:  {m['n_boxes']} en {m['n_lines']} líneas")
    print(f"  height_cv:          {m['height_cv']}")
    print(f"  word_gap mu/cv:     {m['word_gap_mu']} / {m['word_gap_cv']}")
    print(f"  letter_gap mu/cv:   {m['letter_gap_mu']} / {m['letter_gap_cv']}")
    print(f"  baseline σ/autocorr:{m['baseline_sigma']} / {m['baseline_autocorr']}")
    print(f"  slant mean/std:     {m['slant_mean']} / {m['slant_std']}")
    print(f"  line_height_cv:     {m['line_height_cv']}")
    print(f"  left_margin_sigma:  {m['left_margin_sigma']}")
    if m["n_boxes"] < 40 or m["n_lines"] < 3:
        print("⚠ Pocas letras/líneas: escribí una página más llena para "
              "una calibración confiable (≥4 líneas, ≥60 letras).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
