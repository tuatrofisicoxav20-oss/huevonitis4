"""Tests de compute_step_states (lógica pura del stepper U6, sin tkinter)."""
from ui.components.stepper import STEPS, compute_step_states


def test_ningun_paso_hecho_template_es_current():
    states = compute_step_states({
        "has_template": False,
        "has_glyphs": False,
        "coverage_ok": False,
        "has_render": False,
    })
    assert states == {
        "template": "current",
        "capture": "pending",
        "bank": "pending",
        "write": "pending",
    }


def test_flags_faltantes_cuentan_como_false():
    assert compute_step_states({}) == {
        "template": "current",
        "capture": "pending",
        "bank": "pending",
        "write": "pending",
    }


def test_primeros_dos_hechos_bank_es_current():
    states = compute_step_states({
        "has_template": True,
        "has_glyphs": True,
        "coverage_ok": False,
        "has_render": False,
    })
    assert states == {
        "template": "done",
        "capture": "done",
        "bank": "current",
        "write": "pending",
    }


def test_todos_hechos_write_es_current_y_el_resto_done():
    states = compute_step_states({
        "has_template": True,
        "has_glyphs": True,
        "coverage_ok": True,
        "has_render": True,
    })
    assert states == {
        "template": "done",
        "capture": "done",
        "bank": "done",
        "write": "current",
    }


def test_hueco_capture_done_pero_template_sigue_current():
    # has_glyphs True con has_template False: el current es el PRIMER
    # paso no-done (template), aunque capture ya esté completado.
    states = compute_step_states({
        "has_template": False,
        "has_glyphs": True,
        "coverage_ok": False,
        "has_render": False,
    })
    assert states == {
        "template": "current",
        "capture": "done",
        "bank": "pending",
        "write": "pending",
    }


def test_solo_un_paso_es_current_y_cubre_todos_los_pasos():
    combinaciones = [
        {},
        {"has_template": True},
        {"has_template": True, "has_glyphs": True},
        {"has_template": True, "has_glyphs": True, "coverage_ok": True},
        {"has_template": True, "has_glyphs": True, "coverage_ok": True, "has_render": True},
        {"has_glyphs": True, "has_render": True},
    ]
    step_ids = {sid for sid, _label in STEPS}
    for flags in combinaciones:
        states = compute_step_states(flags)
        assert set(states) == step_ids, flags
        assert sum(1 for v in states.values() if v == "current") == 1, flags
        assert set(states.values()) <= {"done", "current", "pending"}, flags
