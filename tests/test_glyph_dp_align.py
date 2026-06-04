"""Salto 3 — alineación global caja↔char por Needleman-Wunsch.

Caso central: una caja EXTRA al inicio de la línea. El mapeo posicional desfasa
todo (cascada); el DP la salta y alinea el resto correctamente.
"""
from core.inkcore.glyph_dp_align import nw_align

# wf_fn local determinista (independiente de la tabla/calibración real).
_WF = {"c": 0.63, "a": 0.80, "s": 0.63, "o": 0.85, "l": 0.40}


def _wf(ch):
    return _WF.get(ch, 0.78)


def test_extra_box_at_start_does_not_cascade():
    ref = list("casa")
    # 5 cajas en orden de lectura: una de ruido al inicio + las 4 reales.
    widths = [0.30, 0.63, 0.80, 0.63, 0.80]
    preds = ["i", "c", "a", "s", "a"]   # 'i' = ruido, no está en "casa"
    confs = [0.9, 0.9, 0.9, 0.9, 0.9]
    mapping = nw_align(widths, preds, confs, ref, _wf)
    # La caja 0 (ruido) NO se empareja; el resto alinea sin desfase.
    assert 0 not in mapping
    assert mapping == {1: 0, 2: 1, 3: 2, 4: 3}


def test_positional_would_have_failed():
    """Demuestra que el mapeo posicional (greedy) SÍ desfasa en el mismo caso."""
    ref = list("casa")
    n = 5
    positional = {i: i for i in range(min(n, len(ref)))}
    # Posicional asigna caja1 (que es la 'c' real) al char1 ('a') → MAL.
    assert positional[1] == 1  # char 'a', pero la caja es 'c'
    # El DP en cambio asigna caja1 → char0 ('c'), correcto.
    mapping = nw_align([0.30, 0.63, 0.80, 0.63, 0.80],
                       ["i", "c", "a", "s", "a"], [0.9] * 5, ref, _wf)
    assert mapping[1] == 0


def test_no_extra_box_aligns_one_to_one():
    ref = list("casa")
    mapping = nw_align([0.63, 0.80, 0.63, 0.80], ["c", "a", "s", "a"],
                       [0.9] * 4, ref, _wf)
    assert mapping == {0: 0, 1: 1, 2: 2, 3: 3}


def test_missing_box_robust():
    # Falta la caja de la 's'. Las cajas presentes son c, a, a.
    ref = list("casa")
    mapping = nw_align([0.63, 0.80, 0.80], ["c", "a", "a"], [0.9] * 3, ref, _wf)
    # c→0, a→1; la última 'a' debe ir al char3 (no al 's' del char2).
    assert mapping[0] == 0
    assert mapping[1] == 1
    assert mapping[2] == 3


def test_empty_inputs():
    assert nw_align([], [], [], list("abc"), _wf) == {}
    assert nw_align([0.5], ["a"], [0.9], [], _wf) == {}
