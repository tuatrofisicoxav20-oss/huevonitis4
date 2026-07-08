"""R16 — tests del export a plotter (vectorize + SVG de trazos)."""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from core.inkcore.renderer_options import RenderOptions

pytest.importorskip("skimage")
pytest.importorskip("sknw")


def _make_bank(tmp_path):
    """Banco sintético: una 'l' (trazo vertical) y una 'o' (anillo)."""
    d = tmp_path / "bank"
    d.mkdir()
    manifest = []
    # 'l': línea vertical de 6px de ancho, 100px de alto, dentro de 128
    for ch, draw in (("l", "line"), ("o", "ring")):
        img = np.zeros((128, 128, 4), dtype=np.uint8)
        if draw == "line":
            img[14:114, 60:66, 3] = 255
        else:
            yy, xx = np.ogrid[:128, :128]
            r = np.sqrt((yy - 64) ** 2 + (xx - 64) ** 2)
            img[(r > 30) & (r < 40), 3] = 255
        path = d / f"{ch}_000.png"
        Image.fromarray(img, "RGBA").save(path)
        ys = np.nonzero(img[:, :, 3])[0]
        manifest.append({
            "char": ch, "image_path": str(path), "tier": "Gold",
            "em_px": 150.0, "nat_h_px": int(ys.max() - ys.min() + 1),
            "baseline_off": float(ys.max() - ys.min()),
        })
    (d / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_skeletonize_line(tmp_path):
    from core.inkcore.plotter.vectorize import StrokeBank, load_stroke_glyph
    bank = StrokeBank(_make_bank(tmp_path))
    g = load_stroke_glyph("l", bank)
    assert g["strokes"], "la 'l' debe producir al menos un trazo"
    # el trazo de una línea vertical es esencialmente 1 polilínea
    assert sum(len(s) for s in g["strokes"]) >= 2


def test_export_svg_structure_and_determinism(tmp_path):
    from core.inkcore.plotter.svg_export import export_svg
    from core.inkcore.plotter.vectorize import StrokeBank
    bank = StrokeBank(_make_bank(tmp_path))
    opts = RenderOptions(render_dpi=150, seed=123)

    out1 = tmp_path / "a.svg"
    out2 = tmp_path / "b.svg"
    r1 = export_svg("lo lo", opts, bank, str(out1))
    export_svg("lo lo", opts, bank, str(out2))

    # determinismo: mismo seed ⇒ archivo idéntico (regla dura del proyecto)
    assert out1.read_text() == out2.read_text()
    assert r1["n_paths"] > 0 and not r1["missing"]

    # SVG válido, en mm 1:1, carta
    root = ET.fromstring(out1.read_text())
    assert root.tag.endswith("svg")
    assert root.attrib["width"] == "215.9mm"
    assert root.attrib["height"] == "279.4mm"
    assert root.attrib["viewBox"] == "0 0 215.9 279.4"
    # hay paths de trazo (pluma-abajo)
    paths = [e for e in root.iter() if e.tag.endswith("path")]
    assert len(paths) >= 1
    assert all(p.attrib["d"].startswith("M ") for p in paths)


def test_dry_run_emits_travel(tmp_path):
    from core.inkcore.plotter.svg_export import export_svg
    from core.inkcore.plotter.vectorize import StrokeBank
    bank = StrokeBank(_make_bank(tmp_path))
    opts = RenderOptions(render_dpi=150, seed=1)
    out = tmp_path / "dry.svg"
    export_svg("lol", opts, bank, str(out), dry_run=True)
    root = ET.fromstring(out.read_text())
    # el grupo de recorrido pluma-arriba va punteado (stroke-dasharray)
    assert any(e.attrib.get("stroke-dasharray") for e in root.iter())
