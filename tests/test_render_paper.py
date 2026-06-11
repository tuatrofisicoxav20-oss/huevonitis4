"""Fase R7 — pase de papel: texturas, skew de escaneo y anclado a renglones.

Valida el contrato de la fase:
  • Las 3 texturas procedurales de assets/papers/ existen y el generador es
    determinista (misma seed → mismos bytes).
  • make_paper texturiza (difiere del sólido) y sin textura es color puro.
  • apply_scan_skew rellena esquinas con el color del papel (sin bordes
    negros) y conserva el tamaño.
  • E10: los baselines del TEXTO caen sobre los renglones impresos
    (y = margin_top + round(k·paso), la misma fórmula que dibuja las rayas)
    con σ < 3 px.
"""
import random
from pathlib import Path

import pytest

try:
    import numpy as np
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

from tests.test_render_realism import _make_stub_bank

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "papers"
TEXTURAS = ["papel_fibra.png", "papel_crema.png", "papel_reciclado.png"]


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_texturas_assets_existen_y_generador_determinista():
    from core.inkcore.renderer_paper import generate_paper_texture
    for name in TEXTURAS:
        path = ASSETS / name
        assert path.exists(), f"falta {name} (corre tools/gen_paper_textures.py)"
        with Image.open(path) as tex:
            assert tex.size == (512, 512)
    # Determinismo del generador: regla del proyecto (misma seed → ídem).
    a = generate_paper_texture(64, 64, random.Random(7))
    b = generate_paper_texture(64, 64, random.Random(7))
    assert list(a.getdata()) == list(b.getdata())


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_make_paper_texturiza_y_sin_textura_es_solido():
    from core.inkcore.renderer import RenderOptions
    from core.inkcore.renderer_paper import make_paper

    liso = make_paper((200, 120), RenderOptions(paper_texture=None), random.Random(1))
    colores = liso.getcolors(maxcolors=4)
    assert colores is not None and len(colores) == 1, "sin textura debe ser sólido"

    tex = make_paper((200, 120), RenderOptions(paper_texture="papel_fibra.png"),
                     random.Random(1))
    assert tex.getcolors(maxcolors=8) is None, "texturizado debe variar píxeles"
    # La modulación es sutil: la media no se aleja del color base (>±12 niveles).
    base = np.asarray(liso, dtype=np.float32).mean()
    mod = np.asarray(tex, dtype=np.float32).mean()
    assert abs(base - mod) < 12.0


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_scan_skew_rellena_esquinas_con_color_papel():
    from core.inkcore.renderer import RenderOptions
    from core.inkcore.renderer_paper import apply_scan_skew

    opts = RenderOptions(scan_skew=True, background_color="#FEFCE8")
    page = Image.new("RGB", (400, 300), "#FEFCE8")
    # Marca negra central para verificar que la rotación ocurrió de verdad.
    page.paste(Image.new("RGB", (60, 8), "#000000"), (170, 146))
    out = apply_scan_skew(page, opts, random.Random(3))
    assert out.size == page.size
    esperado = (0xFE, 0xFC, 0xE8)
    for xy in [(0, 0), (399, 0), (0, 299), (399, 299)]:
        assert out.getpixel(xy) == esperado, f"esquina {xy} no es color papel"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_e10_baselines_anclados_a_renglones(tmp_path):
    """E10: el texto se APOYA en los renglones físicos de la hoja.

    Renderiza con papel liso sin rayas (las y del layout no dependen de la
    decoración) y mide la distancia de cada baseline de texto al renglón
    impreso teórico más cercano (margin_top + round(k·paso), la fórmula de
    _draw_background_decorations): σ < 3 px.
    """
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    renderer = HandwritingRenderer(_make_stub_bank(tmp_path))
    # Solo letras x-height/ascendentes (sin p/q/g/j/y): el baseline se mide
    # como "última fila con tinta densa" y un descendente lo correría abajo.
    texto = "\n".join(["lince mono ave dado kiwi"] * 8)
    opts = RenderOptions(style="", background_style="hoja_blanca",
                         paper_texture=None, scan_skew=False, seed=11,
                         supersample=1, ink_texture_strength=0.0, ink_bleed=0.0)
    pages = renderer.render_pages(texto, opts)
    assert pages

    arr = np.asarray(pages[0].convert("L"), dtype=np.float32)
    tinta = arr < 128  # tinta oscura sobre papel claro
    filas = tinta.sum(axis=1)

    # Clusters de filas con tinta = renglones de texto. Cierre morfológico 1D
    # de huecos pequeños (las franjas casi vacías entre ascendentes y cuerpo
    # partían cada renglón en 2-3 fragmentos). Baseline ≈ última fila con
    # tinta sustancial del cluster.
    paso = opts.line_spacing_px
    umbral = max(2.0, filas.max() * 0.04)
    en_texto = (filas > umbral).astype(np.int8)
    gap_max = max(3, int(paso / 3))
    activo_hasta = -10**9
    cerrado = en_texto.copy()
    for y, a in enumerate(en_texto):
        if a:
            if 0 < y - activo_hasta <= gap_max:
                cerrado[activo_hasta + 1:y] = 1
            activo_hasta = y
    baselines = []
    inicio = None
    for y, activo in enumerate(cerrado):
        if activo and inicio is None:
            inicio = y
        elif not activo and inicio is not None:
            segmento = filas[inicio:y]
            densa = np.where(segmento > segmento.max() * 0.35)[0]
            baselines.append(inicio + int(densa[-1]) if densa.size else y - 1)
            inicio = None
    assert len(baselines) >= 6, f"pocos renglones detectados: {len(baselines)}"

    # Renglones impresos teóricos: la MISMA fórmula que dibuja las rayas.
    esperados = [opts.margin_top_px + round(k * paso) for k in range(1, 60)]
    residuos = [min(abs(b - e) for e in esperados) for b in baselines]
    sigma = float(np.std(residuos))
    assert sigma < 3.0, f"σ del apoyo en renglón = {sigma:.2f}px (residuos {residuos})"
