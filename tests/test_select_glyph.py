"""Tests de GlyphBank.select_glyph: rotación de variantes (Fase 1).

Verifica las tres propiedades del selector de escritura:
  • memoria corta → no repite el mismo glifo en apariciones consecutivas;
  • muestreo ponderado por tier → Bronze nunca entra, Gold/Silver sí rotan;
  • seed reproducible → mismo rng ⇒ misma secuencia.
"""
import random

import numpy as np
import pytest
from PIL import Image

from core.inkcore.bank import GlyphBank
from core.models import GlyphEntry


def _add(bank, char, fname, tier):
    p = bank.bank_dir / fname
    arr = np.zeros((30, 30, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[5:25, 5:25, 3] = 255
    Image.fromarray(arr).save(p)
    bank._entries.append(GlyphEntry(char=char, image_path=str(p), tier=tier, quality_score=0.9))


@pytest.fixture
def bank():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    b = GlyphBank()
    for i in range(6):
        _add(b, "a", f"a_{i}.png", "Gold")
    _add(b, "a", "a_silver.png", "Silver")
    _add(b, "a", "a_bronze.png", "Bronze")
    b._rebuild_indices()
    return b


def test_sin_repeticion_consecutiva(bank):
    hist = {}
    picks = [bank.select_glyph("a", history=hist).image_path for _ in range(40)]
    consec = sum(1 for i in range(1, len(picks)) if picks[i] == picks[i - 1])
    assert consec == 0
    assert len(set(picks)) >= 3  # rota entre varias


def test_bronze_nunca_se_usa(bank):
    hist = {}
    picks = {bank.select_glyph("a", history=hist).image_path for _ in range(200)}
    assert not any(p.endswith("a_bronze.png") for p in picks)
    # Silver sí puede entrar (ponderado, no excluido)
    assert any(p.endswith("a_silver.png") for p in picks)


def test_seed_reproducible(bank):
    r1 = random.Random(123)
    r2 = random.Random(123)
    s1 = [bank.select_glyph("a", history={}, rng=r1).image_path for _ in range(20)]
    s2 = [bank.select_glyph("a", history={}, rng=r2).image_path for _ in range(20)]
    assert s1 == s2


def test_char_inexistente_devuelve_none(bank):
    assert bank.select_glyph("ñ", history={}) is None
