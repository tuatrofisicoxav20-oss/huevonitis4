"""Tests del HandwritingRenderer: word-wrap, no-truncamiento de líneas largas."""
import pytest


@pytest.fixture
def renderer(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_wrap_no_trunca_lineas_largas(renderer):
    """Una línea larga sin saltos manuales debe wrappear, no truncarse.

    Regresión: render_text (ruta <=30 líneas) no aplicaba _soft_wrap_text, así que
    _render_line cortaba (break) en usable_width y se perdía texto — visible en el
    replicador, que llama render_text por bloque. Ahora el canvas crece en alto
    porque el texto se reparte en varias líneas.
    """
    from core.inkcore.renderer import RenderOptions
    opts = RenderOptions()
    corto = renderer.render_text("hola", opts)
    largo = renderer.render_text(" ".join(["palabra"] * 80), opts)
    assert corto is not None and largo is not None
    # Con el bug el largo se truncaba a 1 línea → misma altura que el corto.
    # Con el fix wrappea en muchas líneas → canvas claramente más alto.
    assert largo.height > corto.height * 2, (
        f"el texto largo no wrappeó (largo={largo.height}, corto={corto.height})"
    )


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_respeta_saltos_manuales(renderer):
    """Los \\n del usuario se preservan: N líneas cortas dan más alto que 1."""
    from core.inkcore.renderer import RenderOptions
    opts = RenderOptions()
    una = renderer.render_text("hola", opts)
    cinco = renderer.render_text("a\nb\nc\nd\ne", opts)
    assert una is not None and cinco is not None
    assert cinco.height >= una.height


def test_vertical_class_categorias():
    from core.inkcore.renderer import HandwritingRenderer
    assert HandwritingRenderer._vertical_class("p") == "desc"
    assert HandwritingRenderer._vertical_class("g") == "desc"
    assert HandwritingRenderer._vertical_class("d") == "asc"
    assert HandwritingRenderer._vertical_class("l") == "asc"
    assert HandwritingRenderer._vertical_class("a") == "xheight"
    assert HandwritingRenderer._vertical_class("o") == "xheight"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_recolor_ink_glifo_blanco_se_vuelve_visible():
    """Un glifo del extractor (RGB blanco, forma en alpha) debe recolorearse a la tinta.

    Regresión del bug de texto invisible: sin recolorear, la tinta blanca sobre
    papel claro no se veía. _recolor_ink repinta la forma con ink_color.
    """
    import numpy as np
    from PIL import Image

    from core.inkcore.renderer import HandwritingRenderer
    arr = np.zeros((30, 30, 4), dtype=np.uint8)
    arr[:, :, :3] = 255              # RGB blanco
    arr[8:22, 8:22, 3] = 255         # forma (cuadrado) solo en alpha
    out = HandwritingRenderer._recolor_ink(Image.fromarray(arr), "#1A1A2E")
    oarr = np.asarray(out)
    shape = oarr[:, :, 3] > 128      # donde hay forma
    assert shape.sum() > 0
    # En la forma, el RGB debe ser la tinta (~26,26,46), no blanco
    rgb_in_shape = oarr[:, :, :3][shape].mean(axis=0)
    assert rgb_in_shape[0] < 80 and rgb_in_shape[2] < 90, f"no se recoloreó: {rgb_in_shape}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_produce_tinta_visible(renderer, tmp_path):
    """El render sobre un banco con un glifo blanco produce tinta visible (no 0 px)."""
    import numpy as np
    from PIL import Image

    from core.inkcore.renderer import RenderOptions
    # Inyectar un glifo 'a' blanco (forma en alpha) en el banco aislado
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    renderer.bank.add_glyph("a", str(p))
    img = renderer.render_text("aaa", RenderOptions())
    lum = np.asarray(img.convert("L"))
    assert int((lum < 150).sum()) > 100, "la tinta sigue invisible tras recolorear"


# ── render_document (Ticket 2): flujo estructurado por bloques ──────────────

def _bank_con_a(renderer, tmp_path):
    """Inyecta un glifo 'a' blanco (forma en alpha) en el banco aislado."""
    import numpy as np
    from PIL import Image
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    renderer.bank.add_glyph("a", str(p))


def _doc(blocks):
    from core.ocr.document_model import Document, DocumentPage
    doc = Document(source_path="/tmp/x")
    page = DocumentPage(page_number=1)
    page.blocks = list(blocks)
    doc.pages.append(page)
    return doc


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_document_devuelve_paginas_con_tinta(renderer, tmp_path):
    """Un Document con título + lista + párrafo produce páginas RGB con tinta."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions
    from core.ocr.document_model import BlockType, TextBlock
    _bank_con_a(renderer, tmp_path)
    doc = _doc([
        TextBlock(text="aaa aaa", block_type=BlockType.HEADING, heading_level=1),
        TextBlock(text="aaa", block_type=BlockType.LIST_ITEM),
        TextBlock(text="aaa aaa aaa", block_type=BlockType.PARAGRAPH),
    ])
    pages = renderer.render_document(doc, RenderOptions())
    assert isinstance(pages, list) and pages, "no devolvió páginas"
    lum = np.asarray(pages[0].convert("L"))
    assert int((lum < 150).sum()) > 200, "no se ve tinta en la página"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_document_titulo_mas_grande_que_parrafo(renderer, tmp_path):
    """El mismo texto como HEADING h1 produce más tinta (glifos mayores) que como PARAGRAPH."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions
    from core.ocr.document_model import BlockType, TextBlock
    _bank_con_a(renderer, tmp_path)
    opts = RenderOptions(size_variation=0.0, rotation_range=0.0)
    head = renderer.render_document(
        _doc([TextBlock(text="aaaa", block_type=BlockType.HEADING, heading_level=1)]), opts)
    para = renderer.render_document(
        _doc([TextBlock(text="aaaa", block_type=BlockType.PARAGRAPH)]), opts)
    tinta_head = int((np.asarray(head[0].convert("L")) < 150).sum())
    tinta_para = int((np.asarray(para[0].convert("L")) < 150).sum())
    assert tinta_head > tinta_para * 1.3, (
        f"el h1 no es claramente mayor (head={tinta_head}, para={tinta_para})"
    )


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_document_sin_bloques_cae_a_texto_plano(renderer, tmp_path):
    """Un Document vacío no crashea: cae a render_pages y devuelve al menos una página."""
    from core.inkcore.renderer import RenderOptions
    from core.ocr.document_model import Document
    pages = renderer.render_document(Document(source_path="/tmp/x"), RenderOptions())
    assert isinstance(pages, list) and pages


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_document_cuerpo_snapea_a_renglones_libreta(renderer, tmp_path):
    """En libreta, los renglones de cuerpo caen con período = paso de la grilla.

    El snap alinea cada línea base a un renglón FÍSICO de la hoja (paso
    base_line_h = line_spacing_mm en px al DPI de render). Verificamos que las
    bandas de tinta del cuerpo están espaciadas justo ese paso (y no a la
    deriva entre renglones).
    """
    import numpy as np

    from core.inkcore.renderer import RenderOptions
    from core.ocr.document_model import BlockType, TextBlock
    _bank_con_a(renderer, tmp_path)
    # Sin presets ni ruido vertical para medir el período limpio. font_size se
    # deriva de line_spacing_mm (anclaje físico).
    opts = RenderOptions(
        style="", background_style="libreta",
        size_variation=0.0, rotation_range=0.0, jitter_px=0, baseline_drift=0.0,
    )
    base_line_h = opts.line_height_px  # 7.5 mm a 150 DPI = 44 px
    doc = _doc([TextBlock(text=" ".join(["aaa"] * 60), block_type=BlockType.PARAGRAPH)])
    pages = renderer.render_document(doc, opts)
    lum = np.asarray(pages[0].convert("L"))
    # Filas con tinta del cuerpo (el azul del renglón es claro, >150; la tinta <120).
    row_has_ink = (lum < 120).sum(axis=1) > 5
    # Inicio de cada banda de texto (transición sin-tinta → con-tinta).
    band_tops = [
        i for i in range(1, len(row_has_ink))
        if row_has_ink[i] and not row_has_ink[i - 1]
    ]
    assert len(band_tops) >= 3, f"esperaba varias líneas, vi {len(band_tops)}"
    gaps = np.diff(band_tops)
    # El período entre bandas debe ser el paso de la grilla (±2px por anti-aliasing).
    assert abs(int(np.median(gaps)) - base_line_h) <= 2, (
        f"el cuerpo no quedó pegado a la grilla: gaps={list(gaps)} vs paso={base_line_h}"
    )


# ── Anclaje físico a papel carta (mm → px) ──────────────────────────────────

def test_anclaje_fisico_carta():
    """La geometría default está anclada a carta a 150 DPI y a mm reales."""
    from core.inkcore.renderer import RENDER_DPI, RenderOptions, mm_to_px
    assert mm_to_px(25.4) == RENDER_DPI  # 1 pulgada = DPI px
    opts = RenderOptions()
    assert opts.paper == "letter"
    assert opts.paper_size_px == (1275, 1650)  # 215.9 × 279.4 mm a 150 DPI
    assert opts.page_width == 1275
    assert opts.line_height_px == mm_to_px(7.5)
    # R2: font_size = el renglón físico completo (em); cada glifo se escala
    # por su fracción natural nat_h/em, no a una x-height despejada.
    assert opts.font_size == round(opts.line_spacing_px)


def test_font_size_explicito_se_respeta():
    """Un font_size explícito (encabezados, tests) no se pisa con el derivado."""
    from core.inkcore.renderer import RenderOptions
    assert RenderOptions(font_size=40).font_size == 40


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_pages_interlineado_fisico_exacto(renderer, tmp_path):
    """Texto plano en hoja blanca: bandas de tinta espaciadas EXACTO al renglón
    físico (line_spacing_mm en px), páginas tamaño carta y varias páginas para
    texto largo — el requisito para que cada línea caiga en un renglón real."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions
    _bank_con_a(renderer, tmp_path)
    opts = RenderOptions(
        style="", background_style="hoja_blanca",
        size_variation=0.0, rotation_range=0.0, jitter_px=0,
        baseline_drift=0.0, line_slant_deg=0.0,
        # R14 (Track A): el latente acopla TAMAÑO por glifo y el cramping
        # encoge letras al final del renglón — ambos mueven el tope de la
        # banda de tinta medida; se apagan igual que size_variation.
        hand_energy_sigma=0.0, line_end_cramp=0.0,
    )
    pages = renderer.render_pages("\n".join(["aaa aaa"] * 50), opts)
    assert pages[0].size == (1275, 1650), f"no es carta a 150 DPI: {pages[0].size}"
    assert len(pages) >= 2, "50 líneas deben repartirse en varias páginas carta"
    lum = np.asarray(pages[0].convert("L"))
    row_has_ink = (lum < 120).sum(axis=1) > 5
    band_tops = [
        i for i in range(1, len(row_has_ink))
        if row_has_ink[i] and not row_has_ink[i - 1]
    ]
    assert len(band_tops) >= 10, f"esperaba muchas líneas, vi {len(band_tops)}"
    gaps = np.diff(band_tops)
    # TODOS los avances iguales al renglón físico: si se fuera desfasando
    # línea a línea, el texto no caería sobre los renglones de la hoja.
    assert all(abs(int(g) - opts.line_height_px) <= 1 for g in gaps), (
        f"interlineado no físico: gaps={list(gaps)} vs {opts.line_height_px}"
    )
