"""U0 — lógica no-widget de ui/motion.py y ui/perf.py.

Nada de Tk real: los widgets se simulan con un stub que implementa after/
after_cancel/winfo_exists, suficiente para probar niveles, cancelación y
debounce sin display.
"""
import json

import config
from ui import motion, perf


class FakeWidget:
    """Stub mínimo de un widget Tk para after()/after_cancel()."""

    def __init__(self):
        self.pending: dict[str, object] = {}
        self._n = 0
        self.exists = True

    def after(self, _ms, fn):
        self._n += 1
        key = f"job{self._n}"
        self.pending[key] = fn
        return key

    def after_cancel(self, key):
        self.pending.pop(key, None)

    def winfo_exists(self):
        return self.exists

    def flush(self):
        """Corre todos los after pendientes (incluye los re-agendados)."""
        while self.pending:
            key, fn = next(iter(self.pending.items()))
            del self.pending[key]
            fn()


def _set_level(level):
    motion.set_motion_level(level)


def teardown_function(_fn):
    # Cada test deja el nivel como lo encontró (cache de módulo).
    motion._level = None


# ── Nivel global ─────────────────────────────────────────────────────────────

def test_level_labels_map_to_internal():
    _set_level("Completas")
    assert motion.get_motion_level() == "full"
    _set_level("Reducidas")
    assert motion.get_motion_level() == "reduced"
    _set_level("Off")
    assert motion.get_motion_level() == "off"
    _set_level("off")  # también acepta el nombre interno
    assert motion.get_motion_level() == "off"


def test_invalid_level_falls_back_to_full():
    _set_level("turbo")
    assert motion.get_motion_level() == "full"


def test_level_read_from_settings_file(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"animations": "Reducidas"}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", settings)
    motion._level = None  # forzar relectura
    assert motion.get_motion_level() == "reduced"


def test_level_default_full_without_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "nope.json")
    motion._level = None
    assert motion.get_motion_level() == "full"


def test_should_animate_matrix():
    _set_level("full")
    assert motion.should_animate("motion") and motion.should_animate("color")
    _set_level("reduced")
    assert not motion.should_animate("motion")
    assert motion.should_animate("color")
    _set_level("off")
    assert not motion.should_animate("motion")
    assert not motion.should_animate("color")


# ── animate() ────────────────────────────────────────────────────────────────

def test_animate_off_jumps_to_final_state():
    _set_level("off")
    w = FakeWidget()
    seen = []
    done = []
    motion.animate(w, seen.append, steps=10, on_done=lambda: done.append(True))
    assert seen == [1.0], "en Off debe aplicar SOLO el estado final"
    assert done == [True]
    assert not w.pending, "en Off no se agenda ningún after"


def test_animate_reduced_skips_motion_but_runs_color():
    _set_level("reduced")
    w = FakeWidget()
    seen_motion, seen_color = [], []
    motion.animate(w, seen_motion.append, steps=5, kind="motion")
    assert seen_motion == [1.0] and not w.pending
    motion.animate(w, seen_color.append, steps=5, kind="color")
    w.flush()
    assert len(seen_color) == 5, "color sí anima paso a paso en Reducidas"
    assert seen_color[-1] == 1.0


def test_animate_full_runs_all_steps_and_done():
    _set_level("full")
    w = FakeWidget()
    seen, done = [], []
    motion.animate(w, seen.append, steps=4, on_done=lambda: done.append(True))
    w.flush()
    assert len(seen) == 4 and seen[-1] == 1.0 and done == [True]
    import itertools
    assert all(b >= a for a, b in itertools.pairwise(seen)), "t monótono creciente"


def test_animate_restart_same_key_cancels_previous():
    _set_level("full")
    w = FakeWidget()
    first, second = [], []
    motion.animate(w, first.append, steps=10, key="k")
    motion.animate(w, second.append, steps=3, key="k")
    w.flush()
    # El primer job quedó cancelado tras su primer paso síncrono.
    assert len(first) == 1
    assert len(second) == 3


def test_animate_dead_widget_stops_loop():
    _set_level("full")
    w = FakeWidget()
    seen = []
    motion.animate(w, seen.append, steps=10)
    w.exists = False
    w.flush()
    assert len(seen) == 1, "al morir el widget el loop corta sin reventar"


# ── perf ─────────────────────────────────────────────────────────────────────

def test_measure_decorator_transparent_when_disabled(monkeypatch):
    monkeypatch.setattr(perf, "ENABLED", False)

    @perf.measure("x")
    def fn(a, b=1):
        return a + b

    assert fn(2, b=3) == 5


def test_measure_context_manager_logs_slow_block(monkeypatch, caplog):
    monkeypatch.setattr(perf, "ENABLED", True)
    monkeypatch.setattr(perf, "THRESHOLD_MS", 0.0)
    with caplog.at_level("INFO", logger="huevonitis4.perf"), perf.measure("bloque"):
        pass
    assert any("bloque" in r.message for r in caplog.records)


def test_mark_and_elapsed(monkeypatch):
    monkeypatch.setattr(perf, "ENABLED", True)
    perf.mark("t0")
    ms = perf.elapsed_ms("t0")
    assert ms is not None and ms >= 0
    assert perf.elapsed_ms("inexistente") is None


def test_debounce_collapses_burst_into_one_call():
    w = FakeWidget()
    calls = []
    deb = perf.debounce(w, 300, lambda: calls.append(1))
    deb()
    deb("evento", extra=1)  # acepta y descarta args
    deb()
    assert len(w.pending) == 1, "solo el último after queda vivo"
    w.flush()
    assert calls == [1]
