"""Regresión Fase 0.1: lock en queue/report + lookup por índice del renderer.

El código actual YA toma snapshot bajo _bank_lock en get_review_queue/get_bank_report
(comentario "F7/Fase 1") y YA usa el índice dict _by_char para el lookup por carácter
(PERF-03). Estos tests fijan ese comportamiento para que no reaparezca el bug de
"list changed size during iteration" ni el escaneo lineal O(N).
"""
import threading
import time

import numpy as np
import pytest
from PIL import Image

from core.inkcore.bank import GlyphBank
from core.models import GlyphEntry


def _entry(bank, char, i):
    p = bank.bank_dir / f"{char}_{i:04d}.png"
    if not p.exists():
        arr = np.zeros((20, 20, 4), dtype=np.uint8)
        arr[:, :, :3] = 255
        arr[3:17, 3:17, 3] = 255
        Image.fromarray(arr).save(p)
    return GlyphEntry(char=char, image_path=str(p), tier="Gold", quality_score=0.9)


@pytest.fixture
def big_bank():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    b = GlyphBank()
    chars = "abcdefghijklmnopqrstuvwxyz"
    for c in chars:
        for i in range(40):
            b._entries.append(_entry(b, c, i))
    b._rebuild_indices()
    return b


def test_lookup_usa_indice_por_char(big_bank):
    """El lookup por carácter usa _by_char (O(1)), no escanea self._entries."""
    assert "a" in big_bank._by_char
    assert len(big_bank._by_char["a"]) == 40
    # select_glyph/get_best_glyph devuelven SOLO entradas de ese carácter.
    for _ in range(20):
        e = big_bank.select_glyph("a", history={})
        assert e is not None and e.char == "a"
    assert big_bank.get_best_glyph("m").char == "m"


def test_lookup_es_sublineal(big_bank):
    """1000 lookups en un banco de >1000 entradas deben ser rápidos (índice, no scan)."""
    t0 = time.perf_counter()
    for _ in range(1000):
        big_bank.select_glyph("a", history={})
    dt = time.perf_counter() - t0
    # Con escaneo O(N) por las 1040 entradas sería mucho más lento; el índice lo
    # hace ~constante. Cota generosa para no ser flaky.
    assert dt < 1.0, f"1000 lookups tardaron {dt:.2f}s — ¿se perdió el índice?"


def test_queue_y_report_no_truenan_con_mutacion_concurrente(big_bank):
    """get_review_queue/get_bank_report toman snapshot bajo lock: no 'list changed
    size during iteration' aunque otro hilo mute _entries en paralelo."""
    stop = threading.Event()
    errors = []

    def mutator():
        i = 1000
        while not stop.is_set():
            big_bank._entries.append(_entry(big_bank, "z", i))
            if big_bank._entries:
                big_bank._entries.pop(0)
            i += 1

    t = threading.Thread(target=mutator, daemon=True)
    t.start()
    try:
        for _ in range(200):
            try:
                big_bank.get_review_queue()
                big_bank.get_bank_report()
            except RuntimeError as exc:  # "list changed size during iteration"
                errors.append(exc)
                break
    finally:
        stop.set()
        t.join(timeout=2)
    assert not errors, f"iteración sin lock detectada: {errors}"
