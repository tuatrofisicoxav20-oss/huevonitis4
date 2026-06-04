"""Fase 2 — fusión multi-detector configurable desde config.

Cubre que _build_default_pipeline_config():
  (a) classic_cv solo → config idéntica a la previa (un detector, sin fusión).
  (b) extra disponible → se fusiona con la estrategia configurada.
  (c) extra NO disponible → se omite sin romper (cae a classic_cv solo).
  (d) valor de fusión inválido → cae al default 'cascade'.
"""
from __future__ import annotations

import config
from core.inkcore import glyph_detectors
from core.inkcore.extractor import _build_default_pipeline_config


def _restore(monkeypatch):
    # monkeypatch.setattr ya revierte al terminar el test; este helper solo
    # documenta que tocamos atributos de módulo de config.
    pass


def test_a_classic_cv_solo_es_identico(monkeypatch):
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "classic_cv")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", [])
    cfg = _build_default_pipeline_config()
    assert cfg.detectors == ["classic_cv"]
    # Idéntico a la config legacy: un solo detector, fusión en el default del
    # dataclass ('union'), no forzada.
    assert cfg.detector_fusion == "union"


def test_b_extra_disponible_se_fusiona(monkeypatch):
    # Forzamos que 'easyocr' figure como disponible sin instalar nada.
    monkeypatch.setattr(
        glyph_detectors, "get_available",
        lambda: {"classic_cv": True, "easyocr": True, "craft": False, "paddle_det": False},
    )
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "classic_cv")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", ["easyocr"])
    monkeypatch.setattr(config, "GLYPH_DETECTOR_FUSION", "cascade")
    cfg = _build_default_pipeline_config()
    assert cfg.detectors == ["classic_cv", "easyocr"]
    assert cfg.detector_fusion == "cascade"


def test_c_extra_no_disponible_se_omite(monkeypatch):
    monkeypatch.setattr(
        glyph_detectors, "get_available",
        lambda: {"classic_cv": True, "easyocr": False, "craft": False, "paddle_det": False},
    )
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "classic_cv")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", ["easyocr"])
    cfg = _build_default_pipeline_config()
    # No instalado → se omite, queda classic_cv solo, no rompe.
    assert cfg.detectors == ["classic_cv"]


def test_d_fusion_invalida_cae_a_cascade(monkeypatch):
    monkeypatch.setattr(
        glyph_detectors, "get_available",
        lambda: {"classic_cv": True, "easyocr": True, "craft": False, "paddle_det": False},
    )
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "classic_cv")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", ["easyocr"])
    monkeypatch.setattr(config, "GLYPH_DETECTOR_FUSION", "fusion_que_no_existe")
    cfg = _build_default_pipeline_config()
    assert cfg.detectors == ["classic_cv", "easyocr"]
    assert cfg.detector_fusion == "cascade"


def test_detector_configurado_no_classic_se_suma(monkeypatch):
    # GLYPH_DETECTOR = "easyocr" (no classic) → base classic_cv + easyocr.
    monkeypatch.setattr(
        glyph_detectors, "get_available",
        lambda: {"classic_cv": True, "easyocr": True, "craft": False, "paddle_det": False},
    )
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "easyocr")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", [])
    cfg = _build_default_pipeline_config()
    assert cfg.detectors == ["classic_cv", "easyocr"]


def test_no_duplica_si_extra_repite_el_configurado(monkeypatch):
    monkeypatch.setattr(
        glyph_detectors, "get_available",
        lambda: {"classic_cv": True, "easyocr": True, "craft": False, "paddle_det": False},
    )
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "easyocr")
    monkeypatch.setattr(config, "GLYPH_DETECTORS_EXTRA", ["easyocr", "classic_cv"])
    cfg = _build_default_pipeline_config()
    # easyocr no se duplica y classic_cv (la base) tampoco.
    assert cfg.detectors == ["classic_cv", "easyocr"]
