"""Tests de cobertura del alfabeto (feedback de letras faltantes)."""
from core.inkcore.alphabet_coverage import (
    SPANISH_ALPHABET,
    coverage,
    coverage_message,
    missing_letters,
)  # coverage ya importado para los tests de charset mixto


def test_alfabeto_tiene_27_letras_con_ñ():
    assert len(SPANISH_ALPHABET) == 27
    assert "ñ" in SPANISH_ALPHABET
    assert SPANISH_ALPHABET[14] == "ñ"


def test_faltantes_de_extraccion_real():
    # img1 extrae estas 21; deberían faltar exactamente g m n o x z
    present = list("abcdefhijklpqrstuvwyñ")
    assert missing_letters(present) == ["g", "m", "n", "o", "x", "z"]


def test_cobertura_cuenta_bien():
    have, total, miss = coverage("abc")
    assert have == 3 and total == 27 and len(miss) == 24


def test_completo_no_reporta_faltantes():
    assert missing_letters(SPANISH_ALPHABET) == []
    assert "completo" in coverage_message(SPANISH_ALPHABET, scope="Banco")


def test_ignora_mayusculas_duplicados_y_basura():
    present = ["A", "a", "B", "", None, 3, "c"]
    have, _total, miss = coverage(present)
    assert have == 3  # a, b, c
    assert "a" not in miss and "b" not in miss and "c" not in miss


def test_mensaje_lista_faltantes():
    msg = coverage_message(list("abcdefhijklpqrstuvwyñ"), scope="Banco")
    assert msg.startswith("Banco: 21/27")
    assert "g m n o x z" in msg


def test_charset_con_mayusculas_no_colapsa_caso():
    """Con un charset que incluye MAYÚSCULAS, 'a' y 'A' son distintos."""
    alpha = "abABC"
    # Solo 'a' y 'B' presentes → faltan A, b, C.
    have, total, miss = coverage(["a", "B"], alpha)
    assert total == 5 and have == 2
    # Faltantes en el orden del alfabeto "abABC": b, A, C.
    assert miss == ["b", "A", "C"]


def test_charset_con_digitos():
    have, total, miss = coverage(["0", "5"], "0123456789")
    assert total == 10 and have == 2
    assert "0" not in miss and "5" not in miss


def test_mensaje_charset_completo():
    msg = coverage_message(list("0123456789"), alphabet="0123456789", scope="Dígitos")
    assert "completo" in msg and msg.startswith("Dígitos: 10/10")
