"""Fase 0 — el harness de evaluación corre sin tronar sobre un fixture mínimo.

NO mide calidad del extractor (eso necesita ground-truth real anotado). Solo
verifica que la maquinaria de `tools/eval/run_eval.py` (métricas geométricas,
matching, carga de GT, agregado y `eval_image`) funciona end-to-end. Para no
cargar modelos neuronales en un unit test, se monkeypatchea el extractor con
predicciones canónicas.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from tools.eval import run_eval


def test_iou_basico():
    # Cajas idénticas → IoU 1; disjuntas → 0; solapamiento parcial conocido.
    assert run_eval._iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert run_eval._iou([0, 0, 10, 10], [100, 100, 10, 10]) == 0.0
    # Mitad de solapamiento: inter=50, union=150 → 1/3.
    assert abs(run_eval._iou([0, 0, 10, 10], [5, 0, 10, 10]) - (50 / 150)) < 1e-9


def test_match_hungarian_empareja_optimo():
    pred = [[0, 0, 10, 10], [100, 0, 10, 10]]
    gt = [[100, 0, 10, 10], [0, 0, 10, 10]]
    matches = run_eval._match_hungarian(pred, gt)
    # Cada predicha se empareja con su GT idéntica (IoU 1), sin importar el orden.
    pares = {(i, j) for (i, j, _v) in matches}
    assert pares == {(0, 1), (1, 0)}
    assert all(v == 1.0 for (_i, _j, v) in matches)


def test_match_hungarian_vacio():
    assert run_eval._match_hungarian([], [[0, 0, 1, 1]]) == []
    assert run_eval._match_hungarian([[0, 0, 1, 1]], []) == []


def test_aggregate_ignora_none():
    records = [
        {"mean_iou": 0.8, "char_accuracy": 1.0, "gold_precision": 1.0,
         "gold_rate": 0.5, "n_gt": 2},
        {"mean_iou": None, "char_accuracy": None, "gold_precision": None,
         "gold_rate": 0.0, "n_gt": 0},
    ]
    agg = run_eval._aggregate(records)
    assert agg["n_images"] == 2
    assert agg["n_with_gt"] == 1
    assert agg["mean_iou"] == 0.8  # promedia solo el no-None


def test_eval_image_no_truena_con_gt_minimo(tmp_path, monkeypatch):
    # Imagen falsa (el contenido no importa: monkeypatcheamos el extractor).
    img = tmp_path / "mini.png"
    img.write_bytes(b"\x89PNG\r\n")  # cabecera PNG trivial; no se decodifica

    # GT trivial de 1 caja sobre la imagen "preprocesada".
    gt = {
        "image": "mini.png",
        "reference_text": "a",
        "chars": [{"char": "a", "box": [0, 0, 10, 10]}],
    }
    (tmp_path / "mini.gt.json").write_text(json.dumps(gt), encoding="utf-8")

    # Predicción canónica: una caja que matchea exactamente con char correcto y Gold.
    fake_glyph = SimpleNamespace(char="a", tier="Gold")
    monkeypatch.setattr(run_eval, "_preprocess_image", lambda _p: None)
    monkeypatch.setattr(
        run_eval, "_run_extractor",
        lambda _p, _ref="": ([[0, 0, 10, 10]], [fake_glyph], {}),
    )

    record = run_eval.eval_image(img, label="test")

    assert record["n_pred"] == 1
    assert record["n_gt"] == 1
    assert record["mean_iou"] == 1.0
    assert record["char_accuracy"] == 1.0
    assert record["gold_precision"] == 1.0  # el único Gold es correcto


def test_eval_image_degrada_sin_gt(tmp_path, monkeypatch):
    img = tmp_path / "sin_gt.png"
    img.write_bytes(b"\x89PNG\r\n")
    fake_glyph = SimpleNamespace(char="x", tier="Silver")
    monkeypatch.setattr(run_eval, "_preprocess_image", lambda _p: None)
    monkeypatch.setattr(
        run_eval, "_run_extractor",
        lambda _p, _ref="": ([[1, 2, 3, 4]], [fake_glyph], {}),
    )

    record = run_eval.eval_image(img, label="test")

    # Sin GT: no explota, métricas en None pero reporta el conteo de cajas.
    assert record["n_pred"] == 1
    assert record["mean_iou"] is None
    assert record["char_accuracy"] is None
    # Emite la plantilla .pred.json para editar.
    assert (tmp_path / "sin_gt.pred.json").exists()
