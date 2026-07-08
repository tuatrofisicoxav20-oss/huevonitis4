"""R14 — credibilidad del manuscrito (Tracks A/B/C). Contratos:

  • DETERMINISMO: con seed fija y TODOS los efectos nuevos activos, dos
    renders son byte-idénticos (PNG) y dos fotos son byte-idénticas (JPEG).
  • GATING: con los knobs nuevos en 0, los demás knobs R14 no consumen RNG
    ni alteran un solo byte (rollback: la comparación byte-a-byte contra
    main se hizo al aterrizar cada track; aquí queda el gate ejecutable).
  • ACOPLES: presión positiva oscurece el trazo; el cramping comprime el
    final del renglón.
"""
import hashlib
import io
import random
from pathlib import Path

import pytest

try:
    from PIL import Image  # noqa: F401
    _PIL = True
except ImportError:
    _PIL = False

from tests.test_render_realism import _make_stub_bank

TEXTO = (
    "el viento cruzaba el llano seco y la tarde entera olia a polvo mientras"
    " los cerros se ponian morados a lo lejos\n\n"
    "un cuaderno viejo guardaba la letra de un verano que ya nadie recuerda"
    " con sus renglones torcidos y sus margenes vivos"
)

# Efectos de foto (Track C) al tope razonable, para que el test de
# determinismo ejercite TODOS los caminos nuevos de export_photo.
FOTO_FX = dict(keystone_strength=0.015, desk_background="procedural",
               wb_warmth=0.05, shadow_blob=0.15, focus_gradient=2.0,
               motion_blur=2.0, iso_noise=2.0, chromatic_aberration=0.0012,
               quality_range=(82, 88))


def _renderer(tmp_path):
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


def _png_bytes(pages) -> bytes:
    h = hashlib.sha256()
    for p in pages:
        buf = io.BytesIO()
        p.save(buf, "PNG")
        h.update(buf.getvalue())
    return h.digest()


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_determinismo_render_efectos_on(tmp_path):
    """Mismo seed ⇒ PNG byte-idéntico con latente, cramp y presión activos."""
    from core.inkcore.renderer import RenderOptions

    def _render():
        opts = RenderOptions(seed=31, background_style="hoja_blanca",
                             hand_energy_sigma=0.9, session_shift_prob=0.05,
                             pressure_darkness_coupling=0.25,
                             line_end_cramp=0.2)
        return _renderer(tmp_path).render_pages(TEXTO, opts)

    assert _png_bytes(_render()) == _png_bytes(_render())


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_determinismo_foto_efectos_on(tmp_path):
    """Mismo seed ⇒ JPEG byte-idéntico con TODOS los efectos de Track C."""
    from core.export.photo_export import export_photo
    from core.inkcore.renderer import RenderOptions

    page = _renderer(tmp_path).render_pages(
        TEXTO, RenderOptions(seed=31, background_style="hoja_blanca"))[0]
    outs = []
    for i in range(2):
        out = tmp_path / f"foto_{i}.jpg"
        export_photo(page, out, rng=random.Random(99), **FOTO_FX)
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_gating_knobs_off_no_consumen_rng(tmp_path):
    """Con hand_energy_sigma=0, los acoples dependientes del latente quedan
    muertos: variar session_shift_prob o pressure_darkness_coupling no puede
    cambiar NI UN byte (si cambiara, el gate estaría consumiendo RNG)."""
    from core.inkcore.renderer import RenderOptions

    def _render(**kw):
        opts = RenderOptions(seed=13, background_style="hoja_blanca",
                             hand_energy_sigma=0.0, line_end_cramp=0.0, **kw)
        return _png_bytes(_renderer(tmp_path).render_pages(TEXTO, opts))

    base = _render()
    assert base == _render(session_shift_prob=0.09)
    assert base == _render(pressure_darkness_coupling=0.35)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_foto_defaults_equivalen_a_efectos_en_cero(tmp_path):
    """export_photo sin kwargs ≡ export_photo con los efectos en 0/None:
    los defaults son planos y no corren el stream del RNG (rollback C)."""
    from core.export.photo_export import export_photo
    from core.inkcore.renderer import RenderOptions

    page = _renderer(tmp_path).render_pages(
        TEXTO, RenderOptions(seed=31, background_style="hoja_blanca"))[0]
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    export_photo(page, a, rng=random.Random(5))
    export_photo(page, b, rng=random.Random(5), keystone_strength=0.0,
                 desk_background=None, wb_warmth=0.0, shadow_blob=0.0,
                 focus_gradient=0.0, motion_blur=0.0, iso_noise=0.0,
                 chromatic_aberration=0.0, quality_range=None)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_latente_activo_cambia_la_pagina(tmp_path):
    """Sanidad: el latente encendido produce una página distinta (el efecto
    existe), sin dejar la página vacía ni perder glifos."""
    from core.inkcore.renderer import RenderOptions

    r_on = _renderer(tmp_path)
    on = _png_bytes(r_on.render_pages(TEXTO, RenderOptions(
        seed=13, background_style="hoja_blanca", hand_energy_sigma=0.9)))
    r_off = _renderer(tmp_path)
    off = _png_bytes(r_off.render_pages(TEXTO, RenderOptions(
        seed=13, background_style="hoja_blanca", hand_energy_sigma=0.0)))
    assert on != off
    assert r_on._glyphs_placed == r_off._glyphs_placed


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_presion_oscurece_el_trazo(tmp_path):
    """pressure>0 oscurece el COLOR de tinta del glifo (más depósito) y
    pressure<0 lo aclara. Se mide en el RGB de los píxeles opacos porque
    edge_reconstruct binariza/reconstruye el alpha pero preserva el color
    (ahí es donde la presión debe viajar para sobrevivir el pipeline)."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions

    r = _renderer(tmp_path)
    e = r._select_entry("o")
    assert e and Path(e.image_path).exists()
    opts = RenderOptions(seed=1, warp_strength=0.0, rotation_range=0.0)

    def _ink_level(press):
        img, _ = r._load_glyph(e.image_path, opts, "o", geo=r._geo(e),
                               rotation=0.0, rng=random.Random(3),
                               pressure=press)
        arr = np.asarray(img, dtype=np.float32)
        mask = arr[..., 3] > 200
        return arr[..., :3][mask].mean()

    neutral = _ink_level(0.0)
    assert _ink_level(0.3) < neutral      # presionado = más oscuro
    assert _ink_level(-0.3) > neutral     # liviano = más claro


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_pen_skip_no_toca_stream_del_layout(tmp_path):
    """El skip usa RNG propio sembrado del contenido (patrón del borde R12):
    on/off no puede mover el estado del RNG compartido del layout."""
    from core.inkcore.renderer import RenderOptions

    linea = "montana redonda de tinta continua"
    states = []
    for prob in (0.05, 0.0):
        r = _renderer(tmp_path)
        opts = RenderOptions(seed=3, supersample=1, pen_skip_prob=prob)
        r._begin_render(opts)
        r._render_line(linea, opts, opts.usable_width_px)
        states.append(r._rng.getstate())
    assert states[0] == states[1]


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_apply_pen_skips_unidad():
    """Sobre una barra gruesa el skip despinta un punto interior sin añadir
    tinta; un glifo diminuto (puntuación) vuelve INTACTO (clamp de tamaño)."""
    import numpy as np
    from PIL import Image, ImageDraw

    from core.inkcore.renderer_ink import apply_pen_skips

    bar = Image.new("RGBA", (60, 20), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rectangle([5, 6, 55, 14], fill=(26, 26, 46, 255))
    a0 = np.asarray(bar.getchannel("A"))
    out = apply_pen_skips(bar, random.Random(1), font_size=40)
    a1 = np.asarray(out.getchannel("A"))
    assert ((a1 < 200) & (a0 == 255)).any(), "no despintó nada"
    assert (a1[a0 == 0] == 0).all(), "añadió tinta fuera del trazo"

    dot = Image.new("RGBA", (5, 5), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse([1, 1, 3, 3], fill=(26, 26, 46, 255))
    same = apply_pen_skips(dot, random.Random(1), font_size=40)
    assert np.array_equal(np.asarray(same), np.asarray(dot)), (
        "tocó un glifo diminuto (debe protegerse como la puntuación)")


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_connector_agrega_enlace(tmp_path):
    """Con toda la variación por glifo apagada, connector_prob=1 sólo puede
    AGREGAR tinta (los trazos de enlace) sobre la misma colocación."""
    import numpy as np

    from core.inkcore.renderer import RenderOptions

    def _ink_px(conn):
        r = _renderer(tmp_path)
        opts = RenderOptions(
            seed=5, supersample=1, size_variation=0.0, rotation_range=0.0,
            jitter_px=0, kerning_jitter=0.0, baseline_drift=0.0,
            line_slant_deg=0.0, glyph_slant_drift_deg=0.0, warp_strength=0.0,
            ink_hsv_jitter=(0.0, 0.0), ligature_prob=0.0,
            hand_energy_sigma=0.0, line_end_cramp=0.0,
            # R17: nuevas fuentes de variación por glifo — el skip QUITA tinta
            # y la presión cambia el alpha; se apagan para aislar el conector.
            # R17b: las bolitas AGREGAN tinta en extremos — también se apagan.
            glyph_pressure_jitter=0.0, pen_skip_prob=0.0, ink_blob_strength=0.0,
            connector_prob=conn)
        r._begin_render(opts)
        img = r._render_line("mono nomo", opts, opts.usable_width_px)
        return (np.asarray(img.getchannel("A")) > 0).sum()

    assert _ink_px(1.0) > _ink_px(0.0)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_cramp_comprime_fin_de_renglon(tmp_path):
    """line_end_cramp>0 encoge los huecos del tramo final: la tinta del
    renglón termina ANTES que sin cramp (mismos draws de RNG: el squeeze
    solo multiplica valores ya sorteados)."""
    from core.inkcore.renderer import RenderOptions

    linea = "las letras se aprietan cuando el margen se acerca de verdad"

    def _ancho(cramp):
        r = _renderer(tmp_path)
        opts = RenderOptions(seed=21, hand_energy_sigma=0.0,
                             line_end_cramp=cramp, supersample=1)
        r._begin_render(opts)
        img = r._render_line(linea, opts, opts.usable_width_px)
        return img.getbbox()[2]

    assert _ancho(0.3) < _ancho(0.0)
