"""U2 — el design system se cumple: cero estilos hardcodeados en ui/."""
from tools.check_ui_tokens import find_violations


def test_no_hardcoded_fonts_or_colors_in_ui():
    violations = find_violations()
    assert not violations, (
        "Estilos hardcodeados en ui/ (usa tokens de ui/theme.py):\n"
        + "\n".join(violations)
    )
