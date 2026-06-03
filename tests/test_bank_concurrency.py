"""F7 — concurrencia del banco: add_glyph atómico y lecturas seguras.

Cuatro hilos insertando la MISMA imagen del mismo char deben dejar 1 entrada
(no 4), y sin deadlock (RLock permite que save() re-entre el lock).
"""
import importlib.util
import threading

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "numpy"))
pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/numpy")


def _make_glyph_png(path):
    """Glifo con forma real (hash perceptual NO degenerado, para que el dedup actúe)."""
    import numpy as np
    from PIL import Image
    alpha = np.zeros((48, 34), np.uint8)
    alpha[6:42, 9:15] = 255    # asta vertical
    alpha[6:12, 9:27] = 255    # serif superior
    alpha[36:42, 6:28] = 255   # base
    rgba = np.zeros((48, 34, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = alpha
    Image.fromarray(rgba).save(path)


def test_add_glyph_concurrente_una_sola_entrada(tmp_path):
    from core.inkcore.bank import GlyphBank
    p = tmp_path / "glyph.png"
    _make_glyph_png(p)

    bank = GlyphBank()
    bank.load()

    results = []
    errors = []
    barrier = threading.Barrier(4)

    def worker():
        try:
            barrier.wait(timeout=10)   # arrancar los 4 a la vez → máxima colisión
            results.append(bank.add_glyph("a", str(p)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert all(not t.is_alive() for t in threads), "deadlock: algún hilo no terminó"
    assert not errors, f"errores en hilos: {errors}"
    # Exactamente una inserción real; las otras 3 son duplicados (None).
    entries = bank.get_all(char_filter="a")
    assert len(entries) == 1, f"se insertaron {len(entries)} (race de duplicado)"
    assert sum(1 for r in results if r is not None) == 1


def test_lecturas_concurrentes_con_escrituras_no_rompen(tmp_path):
    """get_all/get_best_glyph/coverage no deben romper mientras otro hilo escribe."""
    from core.inkcore.bank import GlyphBank
    bank = GlyphBank()
    bank.load()

    stop = threading.Event()
    errors = []

    def writer():
        import numpy as np
        from PIL import Image
        i = 0
        while not stop.is_set():
            a = np.zeros((40, 30), np.uint8)
            a[2 + (i % 5):38, 5:25] = 255   # forma variable → no se deduplica
            rgba = np.zeros((40, 30, 4), np.uint8); rgba[..., :3] = 255; rgba[..., 3] = a
            pth = tmp_path / f"w_{i}.png"
            Image.fromarray(rgba).save(pth)
            try:
                bank.add_glyph(chr(ord("a") + (i % 5)), str(pth))
            except Exception as exc:  # noqa: BLE001
                errors.append(("write", exc))
            i += 1

    def reader():
        while not stop.is_set():
            try:
                bank.get_all()
                bank.get_best_glyph("a")
                bank.coverage()
            except Exception as exc:  # noqa: BLE001
                errors.append(("read", exc))

    ts = [threading.Thread(target=writer), threading.Thread(target=reader),
          threading.Thread(target=reader)]
    for t in ts:
        t.start()
    import time
    time.sleep(1.5)
    stop.set()
    for t in ts:
        t.join(timeout=10)
    assert all(not t.is_alive() for t in ts), "deadlock"
    assert not errors, f"lecturas/escrituras concurrentes rompieron: {errors[:3]}"
