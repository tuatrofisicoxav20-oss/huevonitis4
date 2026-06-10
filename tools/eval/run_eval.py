#!/usr/bin/env python3
"""
Salto 0 — Evaluador del extractor de glifos.

Dada una imagen + su ground-truth (<stem>.gt.json), corre el extractor y calcula:
  (a) IoU medio de segmentación (matching húngaro caja predicha <-> caja GT).
  (b) % de carácter correcto sobre cajas BIEN matcheadas (IoU >= umbral).
  (c) tasa de Gold y PRECISIÓN de Gold (de los marcados Gold, cuántos son
      realmente correctos: matcheados con IoU alto Y char correcto).

Las cajas predichas viven en el espacio de la imagen PREPROCESADA (tras
scale/autocrop/deskew). Por eso el evaluador guarda `<stem>.preprocessed.png`:
el ground-truth debe anotarse sobre ESA imagen, no sobre la original. Ver README.

Uso:
    python -m tools.eval.run_eval IMG [IMG ...] [--label SALTO] [--ref-from-gt]
    python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label salto0

Sin ground-truth (o vacío) NO explota: degrada con gracia, reporta cuántas cajas
predijo y emite un .pred.json como plantilla para que el usuario lo corrija.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Permitir ejecutar como script suelto (python tools/eval/run_eval.py …)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

IOU_MATCH_THRESHOLD = 0.5  # IoU mínimo para considerar una caja "bien matcheada"


# ───────────────────────── métricas geométricas ──────────────────────────
def _iou(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _match_hungarian(pred_boxes, gt_boxes):
    """Empareja cajas predichas con GT maximizando el IoU total (asignación óptima).

    Devuelve lista de tuplas (i_pred, j_gt, iou). Usa scipy si está; si no, cae a
    un greedy por mayor-IoU-primero (suficiente para datasets chicos).
    """
    if not pred_boxes or not gt_boxes:
        return []
    n, m = len(pred_boxes), len(gt_boxes)
    iou_mat = [[_iou(pred_boxes[i], gt_boxes[j]) for j in range(m)] for i in range(n)]
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        cost = -np.array(iou_mat)
        rows, cols = linear_sum_assignment(cost)
        out = []
        for r, c in zip(rows, cols):
            if iou_mat[r][c] > 0.0:
                out.append((int(r), int(c), float(iou_mat[r][c])))
        return out
    except Exception:
        # Fallback greedy: ordena todos los pares por IoU desc y asigna sin repetir.
        pairs = sorted(
            ((iou_mat[i][j], i, j) for i in range(n) for j in range(m)),
            reverse=True,
        )
        used_p, used_g, out = set(), set(), []
        for v, i, j in pairs:
            if v <= 0.0 or i in used_p or j in used_g:
                continue
            used_p.add(i)
            used_g.add(j)
            out.append((i, j, v))
        return out


def _norm_char(c: str) -> str:
    return (c or "").strip()[:1]


# ───────────────────────── extracción ──────────────────────────
def _preprocess_image(image_path: str):
    """Reproduce el preprocesado del pipeline (scale/autocrop/deskew) para emitir
    la imagen sobre la que se debe anotar el GT. Devuelve (img_bgr_preprocesada o None)."""
    try:
        import cv2  # noqa: F401

        from core.inkcore.glyph_ingest import ImagePreprocessor, imread_oriented
    except Exception as exc:
        print(f"  ⚠ no se pudo preprocesar ({exc})")
        return None
    img = imread_oriented(image_path)
    if img is None:
        return None
    prep = ImagePreprocessor()
    img = prep.scale(img)
    img = prep.autocrop(img)
    img, _ = prep.deskew(img)
    return img


def _run_extractor(image_path: str, reference_text: str = ""):
    """Corre el pipeline ensemble (camino por defecto) y devuelve (boxes, glyphs, stats)."""
    from core.inkcore.extraction_pipeline import GlyphExtractionPipeline, PipelineConfig
    pipeline = GlyphExtractionPipeline(PipelineConfig())
    result = pipeline.extract(image_path, reference_text)
    return result.boxes, result.glyphs, result.stats


# ───────────────────────── evaluación por imagen ──────────────────────────
def _load_gt(image_path: Path) -> dict | None:
    gt_path = image_path.with_suffix("").with_suffix(".gt.json")
    # acepta tanto ejemplo.gt.json como ejemplo.png.gt.json
    cand = [image_path.parent / (image_path.stem + ".gt.json"), gt_path]
    for c in cand:
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  ⚠ GT ilegible {c.name}: {exc}")
                return None
    return None


def eval_image(image_path: Path, label: str) -> dict:
    print(f"\n── {image_path.name} ──")
    gt = _load_gt(image_path)
    gt_chars = (gt or {}).get("chars", []) if gt else []
    ref_text = (gt or {}).get("reference_text", "") if gt else ""

    # Emitir la imagen preprocesada como referencia de anotación.
    pre = _preprocess_image(str(image_path))
    if pre is not None:
        try:
            import cv2
            out_pre = image_path.parent / (image_path.stem + ".preprocessed.png")
            cv2.imwrite(str(out_pre), pre)
            print(f"  imagen preprocesada → {out_pre.name} (anota el GT sobre ESTA)")
        except Exception as exc:
            print(f"  ⚠ no se pudo guardar preprocessed: {exc}")

    t0 = time.perf_counter()
    try:
        pred_boxes, glyphs, stats = _run_extractor(str(image_path), ref_text)
    except Exception as exc:
        print(f"  ✕ extracción falló: {exc}")
        return {"image": image_path.name, "error": str(exc)}
    elapsed = time.perf_counter() - t0

    n_pred = len(pred_boxes)
    n_gold = sum(1 for g in glyphs if g.tier == "Gold")
    gold_rate = (n_gold / n_pred) if n_pred else 0.0

    record = {
        "image": image_path.name,
        "label": label,
        "n_pred": n_pred,
        "n_gt": len(gt_chars),
        "n_gold": n_gold,
        "gold_rate": round(gold_rate, 3),
        "elapsed_s": round(elapsed, 2),
        "mean_iou": None,
        "char_accuracy": None,
        "gold_precision": None,
    }

    if not gt_chars:
        # Degradación con gracia: sin GT no hay IoU/accuracy. Emitir plantilla.
        print(f"  ⓘ SIN ground-truth → {n_pred} cajas predichas, "
              f"{n_gold} Gold (gold_rate={gold_rate:.2f}). "
              f"IoU/accuracy: N/A (rellena el .gt.json).")
        _emit_pred_template(image_path, pred_boxes, glyphs)
        return record

    gt_boxes = [c["box"] for c in gt_chars]
    matches = _match_hungarian(pred_boxes, gt_boxes)

    mean_iou = sum(v for _, _, v in matches) / len(matches) if matches else 0.0
    well = [(i, j, v) for (i, j, v) in matches if v >= IOU_MATCH_THRESHOLD]
    correct = 0
    for i, j, _ in well:
        if _norm_char(glyphs[i].char) == _norm_char(gt_chars[j]["char"]):
            correct += 1
    char_acc = (correct / len(well)) if well else 0.0

    # Precisión de Gold: de las cajas predichas marcadas Gold, cuántas están
    # bien matcheadas (IoU>=umbral) Y con char correcto.
    gold_idx = {i for i, g in enumerate(glyphs) if g.tier == "Gold"}
    well_map = {i: j for (i, j, _) in well}
    gold_ok = 0
    for i in gold_idx:
        j = well_map.get(i)
        if j is not None and _norm_char(glyphs[i].char) == _norm_char(gt_chars[j]["char"]):
            gold_ok += 1
    gold_prec = (gold_ok / len(gold_idx)) if gold_idx else None

    record.update({
        "mean_iou": round(mean_iou, 3),
        "char_accuracy": round(char_acc, 3),
        "gold_precision": round(gold_prec, 3) if gold_prec is not None else None,
        "n_matched": len(matches),
        "n_well_matched": len(well),
    })
    print(f"  IoU medio={mean_iou:.3f}  char-acc={char_acc:.3f}  "
          f"gold_prec={record['gold_precision']}  "
          f"({len(well)}/{len(gt_chars)} cajas bien matcheadas)")
    return record


def _emit_pred_template(image_path: Path, pred_boxes, glyphs) -> None:
    """Emite un .pred.json con las predicciones como punto de partida editable."""
    out = image_path.parent / (image_path.stem + ".pred.json")
    data = {
        "_nota": "Predicciones del extractor. Corrige char/box y renómbralo a "
                 f"{image_path.stem}.gt.json para evaluar. Coords sobre la imagen "
                 f"{image_path.stem}.preprocessed.png.",
        "image": image_path.name,
        "chars": [
            {"char": g.char, "box": b, "tier": g.tier}
            for g, b in zip(glyphs, pred_boxes)
        ],
    }
    try:
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  plantilla de predicciones → {out.name}")
    except OSError as exc:
        print(f"  ⚠ no se pudo escribir plantilla: {exc}")


# ───────────────────────── agregado + reporte ──────────────────────────
def _aggregate(records: list[dict]) -> dict:
    def _avg(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    return {
        "n_images": len(records),
        "n_with_gt": sum(1 for r in records if r.get("n_gt")),
        "mean_iou": _avg("mean_iou"),
        "char_accuracy": _avg("char_accuracy"),
        "gold_precision": _avg("gold_precision"),
        "gold_rate": _avg("gold_rate"),
    }


def _print_table(records: list[dict], agg: dict) -> None:
    print("\n" + "=" * 78)
    print(f"{'imagen':<28}{'pred':>5}{'gt':>4}{'IoU':>7}{'char%':>8}{'goldP':>7}{'gold%':>7}")
    print("-" * 78)
    for r in records:
        if "error" in r:
            print(f"{r['image']:<28}  ERROR: {r['error']}")
            continue
        def _f(v):
            return f"{v:.2f}" if isinstance(v, (int, float)) else " N/A"
        print(f"{r['image']:<28}{r['n_pred']:>5}{r['n_gt']:>4}"
              f"{_f(r['mean_iou']):>7}{_f(r['char_accuracy']):>8}"
              f"{_f(r['gold_precision']):>7}{_f(r['gold_rate']):>7}")
    print("-" * 78)
    print(f"{'AGREGADO':<28}{'':>5}{agg['n_with_gt']:>4}"
          f"{(f'{agg['mean_iou']:.2f}' if agg['mean_iou'] is not None else ' N/A'):>7}"
          f"{(f'{agg['char_accuracy']:.2f}' if agg['char_accuracy'] is not None else ' N/A'):>8}"
          f"{(f'{agg['gold_precision']:.2f}' if agg['gold_precision'] is not None else ' N/A'):>7}"
          f"{(f'{agg['gold_rate']:.2f}' if agg['gold_rate'] is not None else ' N/A'):>7}")
    print("=" * 78)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluador del extractor de glifos (Salto 0)")
    ap.add_argument("images", nargs="+", help="imágenes a evaluar (acepta globs)")
    ap.add_argument("--label", default="sin-etiqueta",
                    help="etiqueta del salto para comparar corridas (ej. salto3)")
    ap.add_argument("--out-dir", default=str(Path(__file__).parent / "results"),
                    help="dónde guardar el JSON de la corrida")
    args = ap.parse_args(argv)

    # Expandir globs (por si el shell no lo hizo).
    paths: list[Path] = []
    for pat in args.images:
        expanded = _glob.glob(pat)
        paths.extend(Path(p) for p in (expanded or [pat]))
    paths = [p for p in paths if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if not paths:
        print("No se encontraron imágenes (.png/.jpg).")
        return 1

    print(f"Evaluando {len(paths)} imagen(es) — etiqueta '{args.label}'")
    records = [eval_image(p, args.label) for p in paths]
    agg = _aggregate(records)
    _print_table(records, agg)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"eval_{args.label}_{ts}.json"
    out_file.write_text(
        json.dumps({"label": args.label, "timestamp": ts,
                    "aggregate": agg, "per_image": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nCorrida guardada → {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
