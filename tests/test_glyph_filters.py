"""Tests de core/inkcore/glyph_filters — filtros duros, score y gate de captura.

Los glifos sintéticos imitan el formato real del extractor (BUG-18): RGB blanco
con la forma viviendo SOLO en el canal alpha.
"""
import numpy as np
import pytest
from PIL import Image

from core.inkcore.glyph_filters import (
    GlyphMetrics,
    capture_gate,
    compute_char_stats,
    hard_filter_reason,
    measure_glyph,
    quality_score,
)


def _glyph_from_alpha(alpha: np.ndarray) -> Image.Image:
    """Imagen RGBA formato extractor: tinta blanca, forma en alpha."""
    h, w = alpha.shape
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., :3] = 255
    arr[..., 3] = alpha
    return Image.fromarray(arr)


def _ring(size: int = 40, outer: tuple = (10, 30), thick: int = 2) -> Image.Image:
    """Anillo de trazo: densidad realista (~0.35), 1 componente, sin tocar bordes."""
    a = np.zeros((size, size), np.uint8)
    o0, o1 = outer
    a[o0:o1, o0:o1] = 255
    a[o0 + thick:o1 - thick, o0 + thick:o1 - thick] = 0
    return _glyph_from_alpha(a)


def _empty_stats(char: str = "o"):
    return compute_char_stats(char, [])


# ── Filtros duros (umbrales absolutos de fallback, población vacía) ─────────

def test_glifo_bueno_pasa():
    m = measure_glyph(_ring())
    assert not m.empty and m.n_components == 1 and m.edge_cut == ""
    assert hard_filter_reason(m, _empty_stats()) is None


def test_speck_basura_microscopica():
    a = np.zeros((40, 40), np.uint8)
    a[20:23, 20:23] = 255  # mota 3×3
    m = measure_glyph(_glyph_from_alpha(a))
    assert hard_filter_reason(m, _empty_stats())[0] == "SPECK"


def test_ghost_densidad_infima():
    a = np.zeros((60, 60), np.uint8)
    # dos motas mínimas en esquinas opuestas: bbox enorme, tinta casi nula
    a[5:8, 5:8] = 255
    a[52:55, 52:55] = 255
    m = measure_glyph(_glyph_from_alpha(a))
    assert m.density < 0.03
    assert hard_filter_reason(m, _empty_stats())[0] == "GHOST"


def test_blob_manchon_solido():
    a = np.zeros((40, 40), np.uint8)
    a[10:30, 10:30] = 255  # bloque sólido: densidad 1.0
    m = measure_glyph(_glyph_from_alpha(a))
    assert hard_filter_reason(m, _empty_stats())[0] == "BLOB"


def test_clipped_corte_recto_en_borde():
    a = np.zeros((40, 40), np.uint8)
    a[37:40, 0:40] = 255   # franja recta cercenada por el borde inferior
    a[10:37, 18:21] = 255  # trazo vertical que baja hasta la franja
    m = measure_glyph(_glyph_from_alpha(a))
    assert m.edge_cut == "bottom"
    assert hard_filter_reason(m, _empty_stats())[0] == "CLIPPED"


def test_fragmented_componentes_de_mas():
    a = np.zeros((40, 60), np.uint8)
    for x0 in (5, 25, 45):  # tres bloques separados; 'o' espera 1 componente
        a[15:25, x0:x0 + 8] = 255
    m = measure_glyph(_glyph_from_alpha(a))
    assert m.n_components == 3
    assert hard_filter_reason(m, _empty_stats("o"))[0] == "FRAGMENTED"


def test_fragmented_tolera_dos_partes_si_espera_dos():
    a = np.zeros((40, 40), np.uint8)
    a[5:10, 18:22] = 255   # punto de la 'i'
    a[14:34, 18:22] = 255  # palo de la 'i'
    m = measure_glyph(_glyph_from_alpha(a))
    assert m.n_components == 2
    assert hard_filter_reason(m, _empty_stats("i")) is None


def test_outlier_shape_con_poblacion():
    poblacion = [measure_glyph(_ring()) for _ in range(6)]
    st = compute_char_stats("o", poblacion)
    assert not st.fallback
    a = np.zeros((20, 120), np.uint8)  # garabato 5× más ancho que la población
    a[6:14, 4:116] = 255
    a[8:12, 8:112] = 0
    raro = measure_glyph(_glyph_from_alpha(a))
    verdict = hard_filter_reason(raro, st)
    assert verdict is not None and verdict[0] == "OUTLIER_SHAPE"


# ── Score ────────────────────────────────────────────────────────────────────

def test_score_en_rango_y_ordena_bien():
    poblacion = [measure_glyph(_ring()) for _ in range(6)]
    st = compute_char_stats("o", poblacion)
    bueno, _ = quality_score(poblacion[0], st)
    a = np.zeros((40, 40), np.uint8)
    a[10:30, 10:30] = 255
    a[12:28, 12:28] = 0
    a[5:8, 5:8] = 255  # mota extra: componente de más
    feo, _ = quality_score(measure_glyph(_glyph_from_alpha(a)), st)
    assert 0.0 <= feo < bueno <= 100.0


def test_score_glifo_vacio_es_cero():
    m = GlyphMetrics(empty=True)
    score, parts = quality_score(m, _empty_stats())
    assert score == 0.0 and parts == {}


# ── Gate de captura (Fase 7) ────────────────────────────────────────────────

def test_capture_gate_acepta_bueno_rechaza_blob():
    ok, reason = capture_gate(_ring(), "o", [])
    assert ok and reason == ""
    a = np.zeros((40, 40), np.uint8)
    a[10:30, 10:30] = 255
    ok2, reason2 = capture_gate(_glyph_from_alpha(a), "o", [])
    assert not ok2 and reason2.startswith("BLOB")


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"), reason="Pillow not installed")
def test_gate_en_save_template_y_log_de_rechazos(tmp_path):
    """El gate rebota basura en save_template_glyphs_to_bank y la loguea."""
    import config
    from core.inkcore.bank import GlyphBank
    from core.inkcore.template_extract import save_template_glyphs_to_bank

    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    bank = GlyphBank()
    blob = np.zeros((40, 40), np.uint8)
    blob[10:30, 10:30] = 255
    results = [("a", _ring(), 0.9), ("b", _glyph_from_alpha(blob), 0.9)]
    stats = save_template_glyphs_to_bank(results, bank, temp_dir=tmp_path / "tpl")
    assert (stats["saved"], stats["rejected"]) == (1, 1)
    assert {e.char for e in bank.get_all()} == {"a"}
    log = config.TIPOGRAFIA_DIR / "extract_rechazados.csv"
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "BLOB" in content and ",b," in content
