"""F9 — ModelCache con locking POR CLAVE.

Cargar un modelo lento (TrOCR ~400MB) no debe bloquear a quien pide otro modelo
distinto. El lock global anterior congelaba toda la app durante la primera carga.
"""
import threading
import time

import pytest

from core.inkcore.model_cache import ModelCache


@pytest.fixture(autouse=True)
def _clean_cache():
    ModelCache.clear()
    yield
    ModelCache.clear()


def test_distinct_keys_load_in_parallel():
    """El loader de una clave lenta NO debe bloquear el de otra clave."""
    slow_started = threading.Event()
    slow_may_finish = threading.Event()
    fast_done = threading.Event()

    def slow_loader():
        slow_started.set()
        # Se queda colgado hasta que el test lo libere a propósito.
        assert slow_may_finish.wait(timeout=5.0), "slow_loader nunca fue liberado"
        return "SLOW_MODEL"

    def fast_loader():
        return "FAST_MODEL"

    def load_slow():
        ModelCache.get("slow", slow_loader)

    def load_fast():
        ModelCache.get("fast", fast_loader)
        fast_done.set()

    t_slow = threading.Thread(target=load_slow, daemon=True)
    t_slow.start()
    assert slow_started.wait(timeout=2.0), "slow_loader no arrancó"

    # Mientras 'slow' sigue cargando, pedir 'fast' desde otro hilo.
    t_fast = threading.Thread(target=load_fast, daemon=True)
    t_fast.start()

    # Con locking por clave, 'fast' termina aunque 'slow' siga bloqueado.
    assert fast_done.wait(timeout=2.0), (
        "el modelo 'fast' esperó a 'slow' → el lock NO es por clave"
    )
    assert ModelCache.peek("fast") == "FAST_MODEL"

    # Liberar 'slow' y confirmar que termina bien.
    slow_may_finish.set()
    t_slow.join(timeout=2.0)
    assert ModelCache.peek("slow") == "SLOW_MODEL"


def test_loader_exception_leaves_no_corrupt_state():
    """Si el loader lanza, la clave queda ausente (reintentage) y sin lock tomado."""
    calls = {"n": 0}

    def flaky_loader():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo de carga simulado")
        return "OK"

    with pytest.raises(RuntimeError):
        ModelCache.get("flaky", flaky_loader)
    assert ModelCache.peek("flaky") is None  # no quedó estado corrupto

    # Segundo intento: debe poder cargar (el lock no quedó tomado).
    assert ModelCache.get("flaky", flaky_loader) == "OK"
    assert calls["n"] == 2


def test_same_key_loaded_once():
    """Dos hilos pidiendo la MISMA clave la cargan una sola vez."""
    load_count = {"n": 0}
    gate = threading.Event()

    def loader():
        load_count["n"] += 1
        gate.wait(timeout=2.0)
        return object()

    results = {}

    def worker(name):
        results[name] = ModelCache.get("shared", loader)

    t1 = threading.Thread(target=worker, args=("a",), daemon=True)
    t2 = threading.Thread(target=worker, args=("b",), daemon=True)
    t1.start()
    t2.start()
    time.sleep(0.1)
    gate.set()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    assert load_count["n"] == 1, "la clave se cargó más de una vez"
    assert results["a"] is results["b"]  # ambos hilos ven el MISMO objeto
