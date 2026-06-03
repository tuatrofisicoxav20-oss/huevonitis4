"""Tests de las fases de exactitud del extractor (F1–F4 sobre quality.py).

F1: classify_tier único. F2: i/l/m limpias pueden ser Gold. F3: el boost no crea
Golds desde calidad pobre. F4 vive en extraction_pipeline (verificación cruzada).
"""
import importlib.util
import tempfile

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "numpy"))
pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/numpy")


def _glyph_png(ch: str, size: int = 64) -> str:
    """Renderiza una letra limpia en formato del banco (RGB blanco + forma en alpha)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", size)
    except Exception:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    tmp = Image.new("L", (300, 200), 0)
    d = ImageDraw.Draw(tmp)
    bb = d.textbbox((0, 0), ch, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    a = Image.new("L", (w + 8, h + 8), 0)
    ImageDraw.Draw(a).text((4 - bb[0], 4 - bb[1]), ch, fill=255, font=font)
    rgba = Image.new("RGBA", a.size, (255, 255, 255, 0))
    rgba.putalpha(a)
    p = tempfile.mktemp(suffix=".png")
    rgba.save(p)
    return p


# ── F1 ────────────────────────────────────────────────────────────────
def test_classify_tier_cortes():
    from core.inkcore.quality import classify_tier
    assert classify_tier(0.75) == "Gold"
    assert classify_tier(0.80) == "Gold"
    assert classify_tier(0.48) == "Silver"
    assert classify_tier(0.74) == "Silver"
    assert classify_tier(0.47) == "Bronze"
    assert classify_tier(0.0) == "Bronze"


# ── F2 ────────────────────────────────────────────────────────────────
def test_i_y_m_limpias_pueden_ser_gold():
    """El aspecto ya no bloquea a las angostas/anchas: i y m limpias → Gold."""
    from core.inkcore.quality import assess_glyph
    for ch in ("i", "l", "m"):
        res = assess_glyph(_glyph_png(ch))
        assert res["tier"] == "Gold", f"'{ch}' quedó {res['tier']} (score {res['score']})"


def test_basura_clara_no_es_gold():
    """Motas y ruido disperso siguen sin llegar a Gold (la solidez/ink los frena)."""
    from PIL import Image, ImageDraw
    from core.inkcore.quality import assess_glyph
    import random
    # mota diminuta
    a = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(a).ellipse((27, 27, 33, 33), fill=255)
    mota = Image.new("RGBA", a.size, (255, 255, 255, 0)); mota.putalpha(a)
    pm = tempfile.mktemp(suffix=".png"); mota.save(pm)
    assert assess_glyph(pm)["tier"] != "Gold"
    # ruido disperso
    a2 = Image.new("L", (60, 60), 0); d = ImageDraw.Draw(a2)
    random.seed(1)
    for _ in range(40):
        d.point((random.randint(0, 59), random.randint(0, 59)), fill=255)
    ruido = Image.new("RGBA", a2.size, (255, 255, 255, 0)); ruido.putalpha(a2)
    pr = tempfile.mktemp(suffix=".png"); ruido.save(pr)
    assert assess_glyph(pr)["tier"] != "Gold"
