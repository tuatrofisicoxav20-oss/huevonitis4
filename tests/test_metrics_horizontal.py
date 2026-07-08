"""R14 (H5-C1) — tests sintéticos de las métricas de estructura horizontal.

Verifican el CÁLCULO de margin_autocorr / indent_delta / right_ragged_cv sobre
páginas sintéticas de "renglones de cajas" con margen izquierdo CONTROLADO,
sin depender del banco ni del renderer: serie constante → autocorr ≈ 0; serie
OU → > 0.4; sangría conocida → recuperada. El estándar humano lo fijó R3 para
el eje vertical (autocorr > 0.40) y H5 lo extiende al horizontal.
"""
import importlib.util
import random

import pytest

_PIL = importlib.util.find_spec("PIL") is not None

pytestmark = pytest.mark.skipif(not _PIL, reason="Pillow no instalado")

_STEP = 44          # paso vertical entre renglones (px)
_PAGE_W = 1200


def _synthetic_page(x0s, paragraph_starts=None, n_boxes=12, ragged=None):
    """Página sintética: un renglón de cajitas negras por cada x0.

    x0s[i] = x-inicio de tinta del renglón i. paragraph_starts[i]=True deja un
    renglón EN BLANCO antes del i (el hueco doble que detecta la métrica; el
    renglón 0 abre párrafo sin hueco extra). ragged[i] acorta el renglón i esa
    cantidad de px por la derecha. Las cajas varían de alto/ancho de forma
    determinista para parecer letras sin serlo.
    """
    from PIL import Image, ImageDraw

    n = len(x0s)
    starts = paragraph_starts or [False] * n
    img = Image.new("L", (_PAGE_W, 200 + 2 * _STEP * (n + 2)), 255)
    draw = ImageDraw.Draw(img)
    y = 100
    for i, x0 in enumerate(x0s):
        if i > 0:
            y += 2 * _STEP if starts[i] else _STEP
        x = float(x0)
        width_budget = _PAGE_W - 80 - (ragged[i] if ragged else 0)
        for j in range(n_boxes):
            bw = 14 + (i * 7 + j * 5) % 11          # 14..24
            bh = 18 + (i * 5 + j * 3) % 9           # 18..26
            if x + bw > width_budget:
                break
            draw.rectangle((round(x), y - bh, round(x) + bw, y), fill=0)
            x += bw + 8 + (i + j) % 5               # gap 8..12
    return img


def test_margen_constante_autocorr_cero():
    """Margen "de regla": serie constante → residuo nulo → autocorr ≈ 0."""
    from tools.eval_render.metrics import compute_metrics

    m = compute_metrics(_synthetic_page([150.0] * 14))
    assert m["n_lines"] == 14
    assert abs(m["margin_autocorr"]) <= 0.05
    assert m["margin_sigma"] <= 1.0
    assert m["n_paragraphs"] == 1


def test_margen_ou_autocorr_humana():
    """Margen generado por un proceso OU (la referencia humana de R3): la
    métrica debe recuperar la correlación (> 0.4). EN MEDIA sobre 3 seeds:
    el estimador lag-1 por página tiene varianza alta (ver docstring de
    _margin_metrics) y un seed suelto mediría suerte, no señal."""
    from core.inkcore.renderer_noise import OUProcess
    from tools.eval_render.metrics import compute_metrics

    vals = []
    for seed in (7, 0, 2):
        walk = OUProcess(random.Random(seed), sigma=3.0, rho=0.9, bound=12.0)
        x0s = [150.0 + walk.step() for _ in range(30)]
        vals.append(compute_metrics(_synthetic_page(x0s))["margin_autocorr"])
    assert sum(vals) / len(vals) > 0.4


def test_margen_ruido_blanco_autocorr_baja():
    """Jitter i.i.d. por renglón (sin memoria) NO debe pasar por humano."""
    from tools.eval_render.metrics import compute_metrics

    rng = random.Random(3)
    x0s = [150.0 + rng.uniform(-6, 6) for _ in range(30)]
    m = compute_metrics(_synthetic_page(x0s))
    assert m["margin_autocorr"] < 0.3


def test_sangria_conocida_recuperada():
    """4 párrafos con sangría de 35 px → indent_delta_mu ≈ 35 y las primeras
    líneas NO contaminan el margen del cuerpo (sigma chica)."""
    from tools.eval_render.metrics import compute_metrics

    x0s, starts = [], []
    for _p in range(4):
        for i in range(4):
            first = i == 0
            x0s.append(150.0 + (35.0 if first else 0.0))
            starts.append(first)
    m = compute_metrics(_synthetic_page(x0s, paragraph_starts=starts))
    assert m["n_paragraphs"] == 4
    assert m["indent_delta_mu"] == pytest.approx(35.0, abs=4.0)
    assert m["indent_delta_sigma"] <= 4.0
    assert m["margin_sigma"] <= 1.5


def test_parrafos_cortos_no_contaminan_paso_base():
    """El paso base es la mediana de la MITAD BAJA de los pasos: una página
    donde los huecos de párrafo son la mitad de los pasos (párrafos de 2
    renglones) debe seguir detectando todos los párrafos y recuperar la
    sangría con el signo correcto."""
    from tools.eval_render.metrics import compute_metrics

    x0s, starts = [], []
    for _p in range(5):
        x0s.extend([185.0, 150.0])          # sangrada + cuerpo
        starts.extend([True, False])
    m = compute_metrics(_synthetic_page(x0s, paragraph_starts=starts))
    assert m["n_paragraphs"] == 5
    assert m["indent_delta_mu"] == pytest.approx(35.0, abs=4.0)


def test_rag_derecho_informativo():
    """Renglones con corte derecho irregular → right_ragged_cv > 0; las líneas
    de cierre de párrafo (cortas) quedan fuera del cálculo."""
    from tools.eval_render.metrics import compute_metrics

    rng = random.Random(11)
    n = 12
    ragged = [rng.uniform(0, 90) for _ in range(n)]
    m = compute_metrics(_synthetic_page([150.0] * n, ragged=ragged))
    assert m["right_ragged_cv"] > 0.0


def test_pocas_lineas_sin_senal():
    """Con < 3 renglones las métricas horizontales quedan en 0 (sin señal)."""
    from tools.eval_render.metrics import compute_metrics

    m = compute_metrics(_synthetic_page([150.0, 150.0]))
    assert m["margin_autocorr"] == 0.0
    assert m["indent_delta_mu"] == 0.0
