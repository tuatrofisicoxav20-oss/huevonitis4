"""Tests del parser/detector de layout estructurado del Escritor.

Foco: la NO-REGRESIÓN. El test más valioso no es "las marcas parsean bien",
sino "la prosa sin marcas NO se desvía del camino de texto plano". Por eso el
detector se prueba con prosa real (con líneas vacías y sangrías) que NO debe
disparar estructura.
"""
from core.inkcore.writer_structure import (
    StructBlock,
    detect_structure,
    parse_structure,
    render_text_for_coverage,
)


# ── NO-REGRESIÓN: el detector NO debe disparar con prosa normal ──────────────

def test_prosa_con_lineas_vacias_no_dispara():
    """ESTRELLA: prosa multipárrafo (líneas en blanco entre párrafos) NO es
    estructura. Si disparara, toda la prosa normal se desviaría del render de
    hoy → regresión masiva."""
    prosa = (
        "Este es un párrafo normal de apuntes corridos.\n"
        "\n"
        "Otro párrafo después de una línea en blanco, como cualquier texto.\n"
        "\n"
        "Y un tercero para cerrar la idea."
    )
    assert detect_structure(prosa) is False


def test_indentacion_sola_no_dispara():
    """ESTRELLA (anidación): líneas con sangría pero SIN marca no son
    estructura. La sangría sólo se interpreta DENTRO del camino estructurado."""
    texto = (
        "una línea de prosa\n"
        "    otra línea indentada sin ninguna marca\n"
        "\tuna más con tab"
    )
    assert detect_structure(texto) is False


def test_falsos_positivos_no_disparan():
    """El espacio tras la marca es obligatorio: horas, decimales, negativos y
    palabras con guion NO deben confundirse con estructura."""
    for linea in (
        "3:30 nos vemos en la reunión",   # ':' sin espacio después → no numerada
        "1.5 litros de agua",             # '.' seguido de dígito → no numerada
        "5)sin espacio después",          # ')' pegado al texto → no numerada
        "-5°C esta mañana",               # '-' sin espacio → no viñeta
        "well-being y co-working",        # guion interno
        "#hashtag sin espacio",           # '#' pegado → no encabezado
    ):
        # Cada una por separado: ninguna debe disparar.
        assert detect_structure(linea) is False, f"falso positivo: {linea!r}"


# ── Detección positiva ───────────────────────────────────────────────────────

def test_marcas_disparan():
    assert detect_structure("# Título de apunte") is True
    assert detect_structure("## Subtítulo") is True
    assert detect_structure("texto\n1: primer paso") is True
    assert detect_structure("texto\n- una viñeta") is True
    assert detect_structure("* viñeta con asterisco") is True
    assert detect_structure("• viñeta con bullet unicode") is True


# ── Parser: tipos, niveles, marcadores ───────────────────────────────────────

def test_parse_tipos_y_niveles():
    texto = (
        "# Fotosíntesis\n"
        "Las plantas hacen su alimento.\n"
        "1: Captan luz\n"
        "2: Toman CO2\n"
        "- agua\n"
        "- sales minerales"
    )
    blocks = parse_structure(texto)
    kinds = [b.kind for b in blocks]
    assert kinds == [
        "heading", "paragraph", "numbered", "numbered", "bullet", "bullet",
    ]
    assert blocks[0].level == 1
    assert blocks[0].text == "Fotosíntesis"
    assert blocks[2].text == "Captan luz"


def test_heading_niveles():
    blocks = parse_structure("# h1\n## h2\n### h3")
    assert [b.level for b in blocks] == [1, 2, 3]


def test_numerada_conserva_marcador_literal():
    """No se auto-renumera: se conserva el número que tecleó el usuario."""
    blocks = parse_structure("5: empieza en cinco\n7: salta a siete")
    assert blocks[0].kind == "numbered" and blocks[0].marker == "5"
    assert blocks[1].kind == "numbered" and blocks[1].marker == "7"


def test_numerada_acepta_punto_y_parentesis():
    blocks = parse_structure("1. con punto\n2) con paréntesis")
    assert all(b.kind == "numbered" for b in blocks)
    assert [b.marker for b in blocks] == ["1", "2"]


# ── Parser: anidación por sangría ────────────────────────────────────────────

def test_anidacion_indent_level():
    texto = (
        "- nivel base\n"
        "  - dos espacios\n"
        "    - cuatro espacios\n"
        "\t- un tab"
    )
    blocks = parse_structure(texto)
    assert [b.indent_level for b in blocks] == [0, 1, 2, 1]
    assert all(b.kind == "bullet" for b in blocks)


# ── Parser: línea vacía = separación de sección ──────────────────────────────

def test_linea_vacia_marca_seccion_en_siguiente_bloque():
    texto = (
        "# Sección A\n"
        "contenido a\n"
        "\n"
        "# Sección B"
    )
    blocks = parse_structure(texto)
    # La línea vacía no produce bloque; marca gap_section en el siguiente.
    assert len(blocks) == 3
    assert blocks[0].gap_section is False
    assert blocks[1].gap_section is False
    assert blocks[2].gap_section is True  # tras la línea en blanco


def test_parse_devuelve_structblocks():
    blocks = parse_structure("# t")
    assert blocks and isinstance(blocks[0], StructBlock)


# ── Cobertura de glifos: las marcas descartadas no cuentan ───────────────────

def test_render_text_for_coverage_descarta_marcas():
    """Las marcas que no se pintan (#, *, •) no deben aparecer en el texto que
    se usa para avisar de glifos faltantes; los prefijos que SÍ se pintan
    (- , N: ) sí."""
    texto = "# Titulo\n1: uno\n- dos\n* tres"
    cobertura = render_text_for_coverage(texto)
    assert "#" not in cobertura
    assert "*" not in cobertura
    assert "•" not in cobertura
    assert "Titulo" in cobertura          # el contenido del título permanece
    assert "1: uno" in cobertura          # la numerada conserva su prefijo
    assert "- dos" in cobertura           # la viñeta se pinta con guion


def test_render_text_for_coverage_prosa_intacta():
    """Sin marcas, el texto pasa intacto al chequeo de cobertura."""
    prosa = "Texto normal sin marcas.\n\nOtro párrafo."
    assert render_text_for_coverage(prosa) == prosa
