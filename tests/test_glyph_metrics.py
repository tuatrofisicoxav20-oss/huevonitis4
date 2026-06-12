"""Tests R1: métricas geométricas por glifo (manifest v2 retrocompatible).

Cubre: carga de manifests v1 (sin métricas) con defaults, medición real en el
camino del template (canónico y grilla sin fiduciales), persistencia al banco,
estimador heurístico y migrador idempotente.
"""
import importlib.util
import json

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "cv2", "numpy"))

pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/cv2/numpy")


# ── Manifest v1 → v2 (retrocompatibilidad) ──────────────────────────────────

def test_manifest_v1_carga_con_defaults(tmp_path):
    """Un manifest SIN campos de geometría carga con los defaults v2."""
    from PIL import Image

    import config
    from core.inkcore.bank import GlyphBank

    bank_dir = config.TIPOGRAFIA_DIR / config.DEFAULT_PROFILE_ID
    bank_dir.mkdir(parents=True, exist_ok=True)
    png = bank_dir / "a_000.png"
    Image.new("RGBA", (30, 40), (255, 255, 255, 200)).save(png)
    manifest_v1 = [{
        "char": "a", "image_path": str(png), "quality_score": 0.8,
        "tier": "Gold", "ink_coverage": 0.4, "index": 0,
    }]
    (bank_dir / "_manifest.json").write_text(
        json.dumps(manifest_v1), encoding="utf-8")

    bank = GlyphBank()
    entries = bank.get_all("a")
    assert len(entries) == 1
    e = entries[0]
    assert e.baseline_off == -1      # desconocido, NO 0 (0 sería "top")
    assert e.nat_h_px == 0 and e.em_px == 0
    assert e.metrics_source == ""


def test_serializacion_roundtrip_v2():
    """Entry con métricas → dict → entry conserva los campos nuevos."""
    from core.inkcore.bank_serial import entry_from_dict, entry_to_dict
    from core.models import GlyphEntry

    e = GlyphEntry(char="g", image_path="/x/g_000.png", nat_h_px=88,
                   nat_w_px=51, baseline_off=60, em_px=157, lsb=12, rsb=9,
                   metrics_source="template")
    e2 = entry_from_dict(entry_to_dict(e))
    assert (e2.nat_h_px, e2.nat_w_px, e2.baseline_off) == (88, 51, 60)
    assert (e2.em_px, e2.lsb, e2.rsb, e2.metrics_source) == (12 + 145, 12, 9, "template")


# ── Medición en el camino del template ──────────────────────────────────────

def _extraccion_de_plantilla(tmp_path, sin_fiduciales=False):
    """Extrae una plantilla rellena con fuente; opcionalmente tapa los
    marcadores de esquina para forzar la ruta de grilla (_extract_grid)."""
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import TemplateLayout
    from tests.test_template import _fill_sheet

    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    if sin_fiduciales:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        half = lay.fiducial // 2 + 4
        for cx, cy in lay.fiducial_centers():
            draw.rectangle((cx - half, cy - half, cx + half, cy + half),
                           fill="#FFFFFF")
    p = tmp_path / ("grid.png" if sin_fiduciales else "filled.png")
    img.save(p)
    return lay, extract_from_template(str(p), lay)


def test_template_canonico_mide_geometria(tmp_path):
    """La ruta canónica produce baseline_off ≥ 0, em > 0 y nat_h reales."""
    lay, out = _extraccion_de_plantilla(tmp_path)
    assert len(out) >= 25
    _wx, _wy, _ww, wh = lay.writing_rect(0)
    for ch, glyph, _q in out:
        geo = glyph.info.get("geometry")
        assert geo, f"glifo '{ch}' sin geometría"
        assert geo["metrics_source"] == "template"
        assert geo["em_px"] == wh
        assert geo["nat_h_px"] == glyph.height and geo["nat_w_px"] == glyph.width
        assert 0 < geo["baseline_off"] <= geo["nat_h_px"], (
            f"'{ch}': baseline_off={geo['baseline_off']} fuera de rango")
        assert geo["lsb"] >= 0 and geo["rsb"] >= 0
        assert "_ink_top" not in geo  # claves internas limpiadas


def test_template_descendente_baseline_arriba_del_fondo(tmp_path):
    """En 'g/p/q' el baseline queda ARRIBA del fondo del crop (la cola cuelga);
    en 'a/o' queda pegado al fondo de la tinta (asienta en la línea base)."""
    _lay, out = _extraccion_de_plantilla(tmp_path)
    geos = {ch: g.info["geometry"] for ch, g, _q in out}
    for ch in "gpq":
        if ch not in geos:
            continue
        geo = geos[ch]
        # DejaVu: la cola de g/p/q es ~25-30% del alto → el baseline debe
        # quedar claramente despegado del fondo.
        assert geo["baseline_off"] < geo["nat_h_px"] - 8, (
            f"'{ch}': baseline {geo['baseline_off']} pegado al fondo "
            f"{geo['nat_h_px']}")
    for ch in "ao":
        if ch not in geos:
            continue
        geo = geos[ch]
        # bottom de tinta = nat_h - pad (6) salvo clamps de borde.
        assert geo["nat_h_px"] - geo["baseline_off"] <= 12, (
            f"'{ch}': baseline {geo['baseline_off']} no asienta "
            f"(nat_h={geo['nat_h_px']})")


def test_template_grid_sin_fiduciales_tambien_mide(tmp_path):
    """La ruta de grilla (plantilla sin marcadores) también adjunta geometría."""
    _lay, out = _extraccion_de_plantilla(tmp_path, sin_fiduciales=True)
    assert len(out) >= 15, f"la ruta grid extrajo poco: {len(out)}"
    for ch, glyph, _q in out:
        geo = glyph.info.get("geometry")
        assert geo and geo["metrics_source"] == "template", f"'{ch}' sin geometría"
        assert geo["em_px"] > 0
        assert 0 < geo["baseline_off"] <= geo["nat_h_px"]


def test_template_guarda_metricas_al_banco(tmp_path):
    """save_template_glyphs_to_bank persiste la geometría en el manifest."""
    import config
    from core.inkcore.bank import GlyphBank
    from core.inkcore.template_extract import save_template_glyphs_to_bank

    _lay, out = _extraccion_de_plantilla(tmp_path)
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    bank = GlyphBank()
    stats = save_template_glyphs_to_bank(out, bank, temp_dir=tmp_path / "tpl")
    assert stats["saved"] >= 25
    for e in bank.get_all():
        assert e.metrics_source == "template", f"'{e.char}' sin métricas en banco"
        assert e.baseline_off >= 0 and e.em_px > 0 and e.nat_h_px > 0

    # Releer desde disco: las métricas sobreviven el roundtrip del manifest.
    bank2 = GlyphBank()
    assert all(e.metrics_source == "template" for e in bank2.get_all())
    cov = bank2.coverage()
    assert cov["metrics_measured"] == stats["saved"]
    assert cov["metrics_missing"] == 0


# ── Estimador heurístico + migrador ─────────────────────────────────────────

def _banco_legacy_stub(tmp_path):
    """Banco con glifos SIN métricas: x-height (40px), asc (58) y desc (62)."""
    from PIL import Image, ImageDraw

    import config
    from core.inkcore.bank import GlyphBank

    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    bank = GlyphBank()
    gd = tmp_path / "legacy"
    gd.mkdir()
    alturas = {"a": 40, "o": 40, "e": 40, "l": 58, "d": 58, "g": 62, "p": 62}
    bank.begin_batch()
    for ch, h in alturas.items():
        img = Image.new("RGBA", (34, h), (255, 255, 255, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, 31, h - 3), outline=(255, 255, 255, 255), width=4)
        p = gd / f"{ch}.png"
        img.save(p)
        bank.add_glyph(ch, str(p))
    bank.end_batch()
    return bank


def test_migrador_estima_y_es_idempotente(tmp_path):
    from core.inkcore.bank import GlyphBank
    from tools.migrate_metrics import migrate_profile

    bank = _banco_legacy_stub(tmp_path)
    assert all(e.metrics_source == "" for e in bank.get_all())

    stats = migrate_profile(bank.profile_id)
    assert stats["estimated"] == 7

    bank2 = GlyphBank()
    for e in bank2.get_all():
        assert e.metrics_source == "estimada"
        assert e.nat_h_px > 0 and e.em_px > 0 and e.baseline_off > 0
    # Descendentes: baseline arriba del fondo; x-height: baseline en el fondo.
    g = bank2.get_all("g")[0]
    a = bank2.get_all("a")[0]
    assert g.baseline_off < g.nat_h_px - 8
    assert a.nat_h_px - a.baseline_off <= 4

    # Idempotencia byte a byte del manifest.
    manifest = bank2.manifest_file.read_bytes()
    stats2 = migrate_profile(bank.profile_id)
    assert stats2["estimated"] == 0
    assert bank2.manifest_file.read_bytes() == manifest


def test_estimador_nunca_pisa_template(tmp_path):
    """Las métricas medidas de template NO se re-estiman ni con force."""
    from core.inkcore.glyph_metrics import estimate_bank_geometry

    bank = _banco_legacy_stub(tmp_path)
    entries = bank.get_all()
    entries[0].metrics_source = "template"
    updates = estimate_bank_geometry(entries, force=True)
    assert entries[0].image_path not in updates
    assert len(updates) == len(entries) - 1
