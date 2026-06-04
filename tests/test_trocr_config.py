"""Fase 3 — el modelo de TrOCR es configurable vía config.TROCR_MODEL.

Estos tests NO cargan torch ni descargan modelos: solo verifican la resolución
del nombre del modelo (barato) y que el labeler degrada con gracia.
"""
from __future__ import annotations

import config
from core.inkcore.glyph_labelers.trocr_labeler import _DEFAULT_MODEL, TrOCRLabeler


def test_modelo_explicito_gana(monkeypatch):
    lab = TrOCRLabeler(model_name="microsoft/trocr-small-handwritten")
    assert lab.model_name == "microsoft/trocr-small-handwritten"


def test_modelo_se_resuelve_desde_config(monkeypatch):
    monkeypatch.setattr(config, "TROCR_MODEL", "microsoft/trocr-small-handwritten")
    lab = TrOCRLabeler()  # sin arg → toma config
    assert lab.model_name == "microsoft/trocr-small-handwritten"


def test_cae_al_default_si_config_vacio(monkeypatch):
    monkeypatch.setattr(config, "TROCR_MODEL", "")
    lab = TrOCRLabeler()
    assert lab.model_name == _DEFAULT_MODEL


def test_degrada_sin_torch_devuelve_interrogante(monkeypatch):
    # Si transformers/torch no están, label() nunca explota: ('?', 0.0).
    import core.inkcore.glyph_labelers.trocr_labeler as mod
    monkeypatch.setattr(mod, "_TRANSFORMERS_OK", False)
    monkeypatch.setattr(mod, "_TORCH_OK", False)
    lab = TrOCRLabeler()
    assert lab.label(object()) == ("?", 0.0)
    assert lab.label_batch([object(), object()]) == [("?", 0.0), ("?", 0.0)]
