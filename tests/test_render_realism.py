"""Golden de métricas de realismo del renderer (R0, actualizado en R2).

Renderiza una frase fija con seed fija sobre un banco STUB de glifos
sintéticos con proporciones naturales VARIADAS y conocidas (cada char tiene
su propia altura dentro de su clase, como la letra real) y geometría de
template (em=100, baseline medido por construcción).

Línea base R0 (renderer viejo): height_cv 0.20, word_gap_cv 0.04,
baseline_autocorr -0.10, phash_dup_rate 0.77.
R2 (escala proporcional + baseline real) debe subir height_cv a >0.30; el
resto se mueve en R3 (espaciado/deriva) y R5 (dup_rate). Los asserts se
vuelven direccionales conforme cada fase aterriza.
"""
import importlib.util

import pytest

_PIL = importlib.util.find_spec("PIL") is not None

# Sólo a-z y espacios/saltos: el banco stub cubre las 26 minúsculas. Líneas
# < 45 chars para que ninguna dependa del wrap y el snapshot sea estable.
FRASE_PATRON = (
    "el veloz murcielago hindu comia feliz\n"
    "la cigarra zumba bajo el sol que arde\n"
    "joven pesquisa extrana firma de luz"
)

_ASCENDERS = frozenset("bdfhklt")
_DESCENDERS = frozenset("gjpqy")

# El "em" de la hoja stub: las alturas naturales de abajo son fracciones de
# este renglón de captura, igual que en una plantilla real.
STUB_EM = 100


def _stub_dims(char: str) -> tuple[int, int, int]:
    """(alto_total, alto_cuerpo, ancho) naturales del stub para `char`.

    Variados DETERMINISTAMENTE por char dentro de su clase — en letra real
    cada carácter tiene su propia altura (una 'e' no mide lo que una 'o'):
      x-height: 36-46 px de cuerpo; ascendentes: 56-66; descendentes: cuerpo
      36-46 + cola 16-22 hacia abajo.
    """
    k = ord(char)
    body = 36 + (k * 11) % 11           # 36..46
    w = 26 + (k * 7) % 22               # 26..47
    if char in _DESCENDERS:
        tail = 16 + (k * 5) % 7         # 16..22
        return body + tail, body, w
    if char in _ASCENDERS:
        asc = 20 + (k * 3) % 11         # asta 20..30 sobre el cuerpo
        return body + asc, body, w
    return body, body, w


def _stub_glyph(char: str):
    """Glifo sintético estilo banco real: RGB blanco + forma en el alpha.

    Devuelve (imagen, geometry) con la geometría que habría medido el
    template (em=STUB_EM, baseline al pie del cuerpo).
    """
    from PIL import Image, ImageDraw

    k = ord(char)
    h, body, w = _stub_dims(char)
    body_y0 = h - body if char in _ASCENDERS else 0
    body_y1 = body_y0 + body

    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255)
    t = 4  # grosor de trazo

    shape = k % 3
    if shape == 0:
        draw.ellipse((2, body_y0 + 2, w - 3, body_y1 - 3), outline=ink, width=t)
    elif shape == 1:
        draw.arc((2, body_y0 + 2, w - 3, body_y1 - 3), 90, 360, fill=ink, width=t)
        draw.line((w - 5, body_y0 + 6, w - 5, body_y1 - 3), fill=ink, width=t)
    else:
        mid = (body_y0 + body_y1) // 2
        draw.line((2, body_y1 - 3, w // 2, body_y0 + 3), fill=ink, width=t)
        draw.line((w // 2, body_y0 + 3, w - 3, body_y1 - 3), fill=ink, width=t)
        draw.line((4, mid, w - 5, mid), fill=ink, width=t)

    stem_x = 4 + (k * 5) % max(1, w - 10)
    if char in _ASCENDERS:
        draw.line((stem_x, 0, stem_x, body_y1 - 4), fill=ink, width=t)
    elif char in _DESCENDERS:
        draw.line((stem_x, body_y1 - 6, stem_x, h - 2), fill=ink, width=t)
        draw.line((stem_x, h - 4, max(2, stem_x - 8), h - 2), fill=ink, width=t)

    geometry = {
        "nat_h_px": h, "nat_w_px": w,
        "baseline_off": body_y1,        # el cuerpo asienta en la línea base
        "em_px": STUB_EM, "lsb": 0, "rsb": 0,
        "metrics_source": "template",
    }
    return img, geometry


def _make_stub_bank(tmp_path, chars="abcdefghijklmnopqrstuvwxyz",
                    with_geometry=True):
    import config
    from core.inkcore.bank import GlyphBank

    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    bank = GlyphBank()
    glyph_dir = tmp_path / "stub_glyphs"
    glyph_dir.mkdir(exist_ok=True)
    bank.begin_batch()
    for ch in chars:
        img, geo = _stub_glyph(ch)
        p = glyph_dir / f"{f'u{ord(ch)}' if not ch.isalnum() else ch}.png"
        img.save(p)
        bank.add_glyph(ch, str(p), geometry=geo if with_geometry else None)
    bank.end_batch()
    return bank


@pytest.fixture
def stub_renderer(tmp_path):
    """HandwritingRenderer sobre un banco aislado con las 26 minúsculas stub."""
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_golden_metricas_linea_base(stub_renderer):
    """Snapshot de las métricas del renderer con seed fija.

    Una PÁGINA LLENA (15 líneas): con 3 líneas el estimador de autocorr/cv
    tiene tanta varianza de muestreo que el assert mediría suerte, no señal.
    """
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.metrics import compute_metrics

    texto = "\n".join([FRASE_PATRON] * 5)
    # R12: este golden mide la GEOMETRÍA del layout (proporciones, espaciado,
    # baseline) re-detectando cajas sobre los píxeles. La textura de tinta
    # (borde R12 + interior R11) es POSTERIOR a la colocación y NO mueve ni un
    # glifo —probado en test_render_edge.test_edge_no_cambia_colocacion: width y
    # baseline_in idénticos con/sin textura—, pero la tinta sangrada engorda las
    # cajas medidas y sesga height_cv/baseline_autocorr (artefacto del detector,
    # no de la geometría). Se apaga la textura para aislar lo que este test
    # afirma. La textura tiene sus propios tests de invariancia geométrica.
    # R14 (Track A): el latente de mano y el cramping se apagan por la misma
    # razón que la textura — este golden aísla la geometría R2/R3/R5 con la
    # realización con que se calibró; la coherencia macro tiene sus propios
    # tests (test_r14_credibilidad).
    opts = RenderOptions(style="", background_style="hoja_blanca", seed=42,
                         edge_reconstruct=False, ink_texture_v2=False,
                         hand_energy_sigma=0.0, line_end_cramp=0.0)
    pages = stub_renderer.render_pages(texto, opts)
    assert pages, "render_pages no devolvió páginas"
    m = compute_metrics(pages[0])
    print("\nGOLDEN:", m)

    # Sanidad estructural: 15 líneas de texto con cientos de letras.
    assert m["n_lines"] == 15
    assert m["n_boxes"] > 300

    # R2 — escala proporcional + solape leve: el CV de alturas entra al rango
    # humano (>0.30; era 0.20 con la normalización por clase de R-BUG-01).
    assert m["height_cv"] > 0.30
    # R3 — espacio de palabra gauss truncada (E1): cv humano (>0.10; era 0.04).
    assert m["word_gap_cv"] > 0.10
    # R3 — drift OU + jitter correlacionado: el residuo del baseline es un
    # paseo de mano (>0.4; era -0.10, ruido blanco).
    assert m["baseline_autocorr"] > 0.40
    # R5 — warp elástico por instancia: cero sellos incluso con UNA variante
    # por char (era 0.77; el detector está calibrado: ver test anti-sello).
    assert m["phash_dup_rate"] < 0.05


PROSA_PARRAFOS = "\n\n".join([
    "el viento cruzaba el llano seco y la tarde entera olia a polvo mientras"
    " los cerros se ponian morados a lo lejos sin que nadie los mirara y el"
    " camino de tierra seguia solo hasta perderse en la loma",
    "un cuaderno viejo guardaba la letra de un verano que ya nadie recuerda"
    " con sus renglones torcidos y sus margenes que respiran despacio como"
    " respira un animal dormido al fondo de un corral vacio",
    "los grillos cantaban entre las bardas y el pueblo se quedaba quieto"
    " esperando la primera lluvia fuerte que no acababa de llegar nunca"
    " aunque el cielo se cargara de nubes gordas cada tarde de mayo",
    "al final la mano siempre vuelve al margen como el rio a su cauce aunque"
    " cada renglon salga un poco distinto del anterior siempre igual y"
    " siempre nuevo como las olas de un mar chico y terco",
])


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_golden_estructura_horizontal(stub_renderer):
    """R14 (H5-C2) — golden del eje horizontal en prosa de párrafos.

    Prosa de 4 párrafos (línea en blanco = párrafo, camino PLANO), medida en
    los DOS sub-caminos (clásico y snap) con 3 seeds. Gates:
      • margin_sigma: el margen ya no es "de regla" — el camino snap pegaba
        x FIJO (σ=0.14 px medida) y ahora respira (~2 px). Gate duro: separa
        muerto/vivo por un orden de magnitud.
      • margin_autocorr EN MEDIA de las 6 páginas: el estimador lag-1 por
        página (~12 renglones de cuerpo) tiene varianza alta (ver docstring
        de _margin_metrics); el objetivo humano (>0.40) se valida con banco
        real y 5 seeds en RESULTADOS §R14 — aquí el gate ataja regresiones
        (walk muerto o ruido blanco dan ≈ 0).
      • indent_delta: la sangría existe (μ ≈ 0.85·font_size) y VARÍA acotada.
    La prosa con líneas en blanco NO debe disparar el camino estructurado
    (no-regresión aparte en test_writer_structure).
    """
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.metrics import compute_metrics

    autocorrs = []
    for draw_lines in (False, True):
        for seed in (42, 7, 101):
            # R14 (Track A): latente/cramp fuera — este golden mide el eje
            # horizontal de H5-C2 con la realización con que se calibró.
            opts = RenderOptions(style="", background_style="",
                                 draw_lines=draw_lines, seed=seed,
                                 edge_reconstruct=False, ink_texture_v2=False,
                                 hand_energy_sigma=0.0, line_end_cramp=0.0)
            m = compute_metrics(stub_renderer.render_pages(PROSA_PARRAFOS, opts)[0])
            camino = "snap" if draw_lines else "clasico"
            assert m["n_paragraphs"] == 4, f"{camino}/{seed}: párrafos mal detectados"
            assert m["margin_sigma"] > 0.6, (
                f"{camino}/{seed}: margen de regla (σ={m['margin_sigma']})")
            assert 15 <= m["indent_delta_mu"] <= 65, (
                f"{camino}/{seed}: sangría fuera de rango ({m['indent_delta_mu']})")
            assert 2 <= m["indent_delta_sigma"] <= 30, (
                f"{camino}/{seed}: la sangría no varía humano "
                f"({m['indent_delta_sigma']})")
            autocorrs.append(m["margin_autocorr"])
    media = sum(autocorrs) / len(autocorrs)
    assert media > 0.25, f"margen sin correlación de mano: {autocorrs} (media {media:.3f})"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_iter_pages_no_sangra_a_media_oracion(stub_renderer):
    """R14 (H5-C2): iter_pages trocea el texto para exportar página a página;
    un trozo que empieza a MEDIA ORACIÓN no debe sangrar su primera línea
    (las flags de párrafo se calculan sobre el texto completo). Sin la señal
    _first_opens_paragraph, cada salto de página sangraba ~0.85·font_size."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.metrics import (
        _filter_boxes,
        _ink_mask,
        _merge_vertical_parts,
        connected_boxes,
        group_lines,
    )

    rng = __import__("random").Random(5)
    palabras = ["viento", "llano", "cerro", "cuaderno", "verano", "margen",
                "grillo", "barda", "pueblo", "lluvia", "nube", "camino"]
    # UN solo párrafo largo (sin líneas en blanco): todo salto de trozo cae
    # a media oración.
    texto = " ".join(rng.choice(palabras) for _ in range(90))
    opts = RenderOptions(style="", background_style="", seed=42,
                         edge_reconstruct=False, ink_texture_v2=False)
    pages = list(stub_renderer.iter_pages(texto, opts, page_height=500))
    assert len(pages) >= 2, "el texto debe abarcar 2+ páginas para el caso"

    mask = _ink_mask(pages[1])
    h, w = mask.shape
    boxes = _filter_boxes(connected_boxes(mask), w, h)
    lines = [_merge_vertical_parts(ln) for ln in group_lines(boxes, mask)]
    assert len(lines) >= 3
    x0s = [float(ln[0][0]) for ln in lines]
    delta = abs(x0s[0] - float(np.median(x0s[1:])))
    assert delta < 14, (
        f"la primera línea de la página 2 sangró {delta:.0f}px a media oración")


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_lorem_500_palabras_cero_perdida(stub_renderer):
    """E4/R-BUG-07: un texto largo no pierde NI UN glifo al renderizar.

    Cuenta los glifos pegados (contador del renderer) contra los caracteres
    no-espacio pedidos. El banco stub cubre todo el alfabeto del texto, así
    que cada char debe terminar pegado en alguna página.
    """
    import random as _random

    from core.inkcore.renderer import RenderOptions

    rng = _random.Random(7)
    palabras = ["lorem", "ipsum", "dolor", "amet", "consectetur", "adipiscing",
                "sed", "tempor", "labore", "magna", "veniam", "exercitation",
                "ullamco", "aliquip", "commodo", "duis", "aute", "voluptate",
                "cillum", "fugiat", "pariatur", "excepteur", "occaecat", "qui"]
    texto = " ".join(rng.choice(palabras) for _ in range(500))
    esperados = sum(1 for c in texto if not c.isspace())

    opts = RenderOptions(style="", background_style="hoja_blanca", seed=3)
    pages = stub_renderer.render_pages(texto, opts)
    assert len(pages) >= 1
    assert not stub_renderer.last_missing_chars()
    assert stub_renderer._glyphs_placed == esperados, (
        f"se perdieron {esperados - stub_renderer._glyphs_placed} glifos "
        f"de {esperados}")


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_mayusculas_usan_glifo_exacto(tmp_path):
    """R-BUG-03: con 'A' en el banco, la 'A' NO renderiza el glifo de 'a'.

    La 'A' stub es claramente más alta que la 'a' (66 vs 40 px naturales);
    si el lookup eligiera la minúscula, la altura de tinta del render sería
    la de una x-height.
    """
    import numpy as np
    from PIL import Image

    import config
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    bank = GlyphBank()
    gd = tmp_path / "g"
    gd.mkdir()
    for ch, h in (("a", 40), ("A", 66)):
        Image.new("RGBA", (40, h), (255, 255, 255, 0))
        arr = np.zeros((h, 40, 4), dtype=np.uint8)
        arr[:, :, :3] = 255
        arr[2:h - 2, 4:36, 3] = 255
        Image.fromarray(arr).save(gd / f"{ch}_x.png")
        bank.add_glyph(ch, str(gd / f"{ch}_x.png"), geometry={
            "nat_h_px": h, "nat_w_px": 40, "baseline_off": h - 2,
            "em_px": 100, "lsb": 0, "rsb": 0, "metrics_source": "template",
        })
    r = HandwritingRenderer(bank)
    opts = RenderOptions(style="", background_style="hoja_blanca",
                         size_variation=0.0, rotation_range=0.0, seed=1)
    img_A = r.render_pages("AAAA", opts)[0]
    assert not r.last_case_downgraded()
    img_a = r.render_pages("aaaa", opts)[0]
    h_A = _ink_height(img_A)
    h_a = _ink_height(img_a)
    assert h_A > h_a * 1.4, f"la A ({h_A}px) no es más alta que la a ({h_a}px)"

    # Sin glifo exacto: cae a la minúscula y lo REGISTRA (no es missing).
    r.render_pages("BBBB", opts)
    assert r.last_case_downgraded() == {"B"} or "B" in r.last_missing_chars()


def _ink_height(page) -> int:
    import numpy as np
    lum = np.asarray(page.convert("L"))
    rows = np.where((lum < 150).sum(axis=1) > 0)[0]
    return int(rows.max() - rows.min() + 1) if len(rows) else 0


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_coverage_report_detecta_downgrade_de_caso(stub_renderer):
    """coverage_report distingue missing real de mayúscula sin glifo propio."""
    rep = stub_renderer.coverage_report("Hola 12 ñu")
    assert "H" in rep["covered"] and "H" in rep["case_downgraded"]
    assert set("12ñ") <= set(rep["missing"])
    assert "u" in rep["covered"] and "u" not in rep["case_downgraded"]


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_anti_sello_bilateral(stub_renderer):
    """R5 (C3/C4): el detector de sellos FUNCIONA y el render lo pasa.

    Bilateral a propósito: con el pipeline de variación APAGADO el dup_rate
    debe dispararse (si no, la métrica se volvió ciega y el assert de abajo
    no probaría nada); con R5 activo debe caer a <5% AUN con una sola
    variante por carácter.
    """
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.metrics import compute_metrics

    sello = RenderOptions(style="", background_style="hoja_blanca", seed=42,
                          rotation_range=0.0, size_variation=0.0,
                          warp_strength=0.0, glyph_slant_drift_deg=0.0,
                          line_slant_deg=0.0, kerning_jitter=0.0,
                          jitter_px=0, baseline_drift=0.0,
                          # R6: también la tinta debe ser de sello — el value
                          # noise/bleed/micro-color ya rompen el hash por sí
                          # solos y este es el control NEGATIVO del detector.
                          ink_texture_strength=0.0, ink_bleed=0.0,
                          ink_hsv_jitter=(0.0, 0.0), supersample=1,
                          # R14/R15: las fuentes nuevas de variación también
                          # se apagan en el control negativo (presión por
                          # posición y skips rompían el hash de unas letras
                          # y el gate >0.85 medía eso, no al detector).
                          hand_energy_sigma=0.0, line_end_cramp=0.0,
                          pen_skip_prob=0.0, ink_stroke_space=False)
    m_sello = compute_metrics(stub_renderer.render_pages(FRASE_PATRON, sello)[0])
    assert m_sello["phash_dup_rate"] > 0.85, (
        f"el detector dejó de ver sellos: {m_sello['phash_dup_rate']}")

    humano = RenderOptions(style="", background_style="hoja_blanca", seed=42)
    m_humano = compute_metrics(stub_renderer.render_pages(FRASE_PATRON, humano)[0])
    assert m_humano["phash_dup_rate"] < 0.05, (
        f"efecto sello vivo: {m_humano['phash_dup_rate']}")


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_misma_seed_png_identico(stub_renderer):
    """R3 (C8/I6): misma seed → MISMOS bytes; seeds distintas → distintos.

    El RNG inyectado no toca el random global: un render seedeado en paralelo
    con la extracción no debe alterar el azar del resto del proceso.
    """
    import io
    import random as _random

    from core.inkcore.renderer import RenderOptions

    def _png_bytes(seed):
        opts = RenderOptions(style="", background_style="hoja_blanca", seed=seed)
        page = stub_renderer.render_pages(FRASE_PATRON, opts)[0]
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        return buf.getvalue()

    estado_global = _random.getstate()
    a = _png_bytes(123)
    b = _png_bytes(123)
    c = _png_bytes(124)
    assert a == b, "misma seed produjo PNGs distintos"
    assert a != c, "seeds distintas produjeron el mismo PNG"
    assert _random.getstate() == estado_global, "el render tocó el random global"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_char_faltante_deja_marca_visible_siempre(stub_renderer):
    """R3/H8 + fix-puente: un char sin glifo NUNCA se omite en silencio.
    Deja SIEMPRE una marca VISIBLE (placeholder rojo subrayado), con o sin
    allow_font_fallback, y se reporta en missing_chars — así "subió" no se
    vuelve "subi" sin dejar rastro en un PDF real."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions

    def _rojo(page):
        arr = np.asarray(page.convert("RGB")).astype(int)
        rojo = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 100) & (arr[:, :, 2] < 100)
        return int(rojo.sum())

    # Export real (allow_font_fallback=False): antes se omitía en silencio;
    # ahora deja la marca roja igual, y lo registra como faltante.
    opts = RenderOptions(style="", background_style="hoja_blanca", seed=5)
    pages = stub_renderer.render_pages("@@@", opts)
    assert stub_renderer.last_missing_chars() == {"@"}
    assert _rojo(pages[0]) > 20, "el char faltante no dejó marca visible en export"

    # Preview (allow_font_fallback=True): sigue marcando en rojo.
    opts2 = RenderOptions(style="", background_style="hoja_blanca", seed=5,
                          allow_font_fallback=True)
    pages2 = stub_renderer.render_pages("@@@", opts2)
    assert _rojo(pages2[0]) > 20, "el preview no marcó el faltante en rojo"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_compare_cli_corre_sobre_dos_pngs(stub_renderer, tmp_path):
    """compare.py funciona end-to-end sobre dos PNGs cualesquiera."""
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.compare import main

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    stub_renderer.render_pages(
        FRASE_PATRON, RenderOptions(style="", background_style="hoja_blanca", seed=1)
    )[0].save(a)
    stub_renderer.render_pages(
        FRASE_PATRON, RenderOptions(style="", background_style="hoja_blanca", seed=2)
    )[0].save(b)
    out_json = tmp_path / "cmp.json"
    rc = main([str(a), str(b), "--json", str(out_json)])
    assert rc == 0
    assert out_json.exists()


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_ab_sheet_baraja_y_mapea(stub_renderer, tmp_path):
    """R9 (H1/H6): la hoja A/B trae 2N tiras barajadas y el mapa las nombra."""
    import random as _random

    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.ab_sheet import build_ab_sheet

    opts = RenderOptions(style="", background_style="hoja_blanca", seed=4)
    synth = stub_renderer.render_pages(FRASE_PATRON, opts)[0]
    real = stub_renderer.render_pages(FRASE_PATRON.upper().lower(), opts)[0]
    sheet, mapping = build_ab_sheet(real, synth, _random.Random(7), n_strips=4)
    assert len(mapping) == 8
    assert sorted(set(mapping.values())) == ["real", "synth"]
    assert list(mapping.values()).count("real") == 4
    assert sheet.height > 8 * 100  # 8 tiras apiladas
