"""Salto 0 — tests de las métricas del evaluador (tools/eval/run_eval).

Verifican el cálculo puro (IoU, matching, char-accuracy, gold-precision) sin
depender de correr el extractor ni de ground-truth real.
"""
import pytest

from tools.eval.run_eval import _iou, _match_hungarian, _norm_char


def test_iou_basic():
    assert _iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert _iou([0, 0, 10, 10], [100, 0, 10, 10]) == 0.0
    # solapamiento parcial: inter=25, union=175
    assert _iou([0, 0, 10, 10], [5, 5, 10, 10]) == pytest.approx(25 / 175, abs=1e-4)


def test_match_hungarian_optimal_pairing():
    # 2 predichas, 2 GT; el matching debe emparejar las que solapan.
    pred = [[0, 0, 10, 10], [100, 0, 10, 10]]
    gt = [[101, 0, 10, 10], [1, 1, 10, 10]]
    matches = _match_hungarian(pred, gt)
    pairing = {i: j for i, j, _ in matches}
    assert pairing == {0: 1, 1: 0}  # pred0↔gt1, pred1↔gt0


def test_match_hungarian_empty():
    assert _match_hungarian([], [[0, 0, 1, 1]]) == []
    assert _match_hungarian([[0, 0, 1, 1]], []) == []


def test_char_accuracy_and_gold_precision_logic():
    """Reproduce el cálculo de char-acc y gold-precision de eval_image con datos
    sintéticos, para fijar la semántica sin correr el extractor."""
    from dataclasses import dataclass

    @dataclass
    class _G:
        char: str
        tier: str

    # 3 cajas predichas, todas bien matcheadas con GT (IoU=1).
    pred = [[0, 0, 10, 10], [20, 0, 10, 10], [40, 0, 10, 10]]
    glyphs = [_G("a", "Gold"), _G("x", "Gold"), _G("c", "Silver")]
    gt = [{"char": "a", "box": [0, 0, 10, 10]},
          {"char": "b", "box": [20, 0, 10, 10]},
          {"char": "c", "box": [40, 0, 10, 10]}]

    matches = _match_hungarian(pred, [g["box"] for g in gt])
    well = [(i, j, v) for i, j, v in matches if v >= 0.5]
    correct = sum(1 for i, j, _ in well
                  if _norm_char(glyphs[i].char) == _norm_char(gt[j]["char"]))
    # a==a ✓, x!=b ✗, c==c ✓ → 2/3
    assert correct == 2
    assert len(well) == 3

    # Gold: índices 0 (a, correcto) y 1 (x, incorrecto) → precisión 1/2.
    well_map = {i: j for i, j, _ in well}
    gold_idx = [i for i, g in enumerate(glyphs) if g.tier == "Gold"]
    gold_ok = sum(1 for i in gold_idx
                  if _norm_char(glyphs[i].char) == _norm_char(gt[well_map[i]]["char"]))
    assert gold_idx == [0, 1]
    assert gold_ok == 1  # solo la 'a'; gold_precision = 1/2 = 0.5
