"""Tests for GlyphBank: add/dedup/remove/reload with tmp_path."""
import shutil
from pathlib import Path

import pytest


def _make_test_png(path: Path, px: int = 20):
    """Create a tiny solid-white RGBA PNG for testing."""
    try:
        from PIL import Image
        img = Image.new("RGBA", (px, px), (0, 0, 0, 255))
        img.save(path)
        return True
    except ImportError:
        return False


@pytest.fixture
def bank(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    return GlyphBank()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_add_glyph(bank, tmp_path):
    src = tmp_path / "glyph.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("a", str(src))
    assert entry is not None
    assert entry.char == "a"
    assert Path(entry.image_path).exists()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_add_and_reload(bank, tmp_path):
    src = tmp_path / "glyph_b.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    bank.add_glyph("b", str(src))
    from core.inkcore.bank import GlyphBank
    bank2 = GlyphBank()
    entries = bank2.get_all(char_filter="b")
    assert len(entries) >= 1
    assert entries[0].char == "b"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_remove_glyph(bank, tmp_path):
    src = tmp_path / "glyph_c.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("c", str(src))
    assert entry is not None
    bank.remove_glyph(entry)
    entries = bank.get_all(char_filter="c")
    assert len(entries) == 0
    assert not Path(entry.image_path).exists()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_dedup_identical_images(bank, tmp_path):
    """Dos copias idénticas de un glifo CON FORMA deben deduplicarse.

    Usa un glifo con forma (hash perceptual con señal), no una imagen sólida:
    el dedup confía en el hash perceptual, y una imagen plana produce un hash
    degenerado que ya no se usa para deduplicar (es basura sin forma, ver
    test_dedup_robusto_con_basura_degenerada).
    """
    src1 = tmp_path / "dup1.png"
    src2 = tmp_path / "dup2.png"
    if not _make_alpha_glyph(src1, "ellipse"):
        pytest.skip("PIL not available")
    shutil.copy2(src1, src2)
    bank.add_glyph("d", str(src1))
    result2 = bank.add_glyph("d", str(src2))
    # Copias idénticas con forma → mismo hash → rechazadas como duplicado
    assert result2 is None


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_skip_dedup_guarda_casi_identicos(bank, tmp_path):
    """skip_dedup=True guarda muestras casi idénticas de la misma letra.

    Es el flujo de PLANTILLA con repeats>1: la misma letra repetida a propósito
    para capturar variación. Con skip_dedup=True deben entrar las 3 (saved=3,
    dupes=0); con el default (False) al menos una se rechaza como duplicado.
    """
    srcs = [tmp_path / f"tpl_{i}.png" for i in range(3)]
    if not _make_alpha_glyph(srcs[0], "ellipse"):
        pytest.skip("PIL not available")
    # Casi idénticas: mismo glifo copiado (hashes iguales → dedup las uniría).
    for s in srcs[1:]:
        shutil.copy2(srcs[0], s)

    saved = dupes = 0
    for s in srcs:
        if bank.add_glyph("e", str(s), skip_dedup=True) is None:
            dupes += 1
        else:
            saved += 1
    assert (saved, dupes) == (3, 0)

    # Contraste: con el default, las copias idénticas se deduplican.
    dup_srcs = [tmp_path / f"def_{i}.png" for i in range(3)]
    for d in dup_srcs:
        shutil.copy2(srcs[0], d)
    def_dupes = 0
    for d in dup_srcs:
        if bank.add_glyph("f", str(d)) is None:
            def_dupes += 1
    assert def_dupes > 0


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_save_template_conserva_score_y_tier(bank):
    """save_template_glyphs_to_bank preserva el score de la plantilla.

    El _q ya calculado (con la rebaja a 0.45 que el CNN da a casillas dudosas)
    debe llegar al banco vía quality_override en vez de recalcularse: la muestra
    floja cae a Bronze y la buena de otra hoja queda Gold, así get_best_glyph
    elige la buena.
    """
    import numpy as np
    from PIL import Image

    from core.inkcore.template_extract import save_template_glyphs_to_bank
    arr = np.zeros((40, 40, 4), np.uint8)
    arr[..., :3] = 255
    arr[10:30, 10:30, 3] = 255  # bloque de tinta en el alpha
    glyph = Image.fromarray(arr)  # 4 canales → RGBA
    # Misma letra en dos hojas: una dudosa (CNN la fijó en 0.45) y una buena.
    results = [("a", glyph.copy(), 0.45), ("a", glyph.copy(), 0.90)]
    stats = save_template_glyphs_to_bank(results, bank)
    assert (stats["saved"], stats["dupes"]) == (2, 0)

    by_score = {round(e.quality_score, 2): e for e in bank.get_all() if e.char == "a"}
    assert set(by_score) == {0.45, 0.90}, by_score
    assert by_score[0.45].tier == "Bronze"   # < TIER_SILVER (0.48)
    assert by_score[0.90].tier == "Gold"     # >= TIER_GOLD (0.75)


def _make_alpha_glyph(path: Path, shape: str = "ellipse", px: int = 48):
    """Crea un glifo estilo-extractor: tinta BLANCA con la forma en el alpha.

    Reproduce el formato real que rompía el dedup: RGB=255 en toda la imagen,
    forma codificada solo en el canal alpha (0=fondo, 255=trazo).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGBA", (px, px), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255)
    if shape == "ellipse":
        d.ellipse([8, 8, px - 8, px - 8], outline=ink, width=4)
    elif shape == "rect":
        d.rectangle([6, 12, px - 6, px - 12], outline=ink, width=4)
    elif shape == "line":
        d.line([4, 4, px - 4, px - 4], fill=ink, width=5)
    img.save(path)
    return True


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_dhash_not_degenerate_for_alpha_ink(tmp_path):
    """El glifo del extractor (tinta en alpha) debe producir un hash con señal.

    Regresión del bug: _flatten_rgba pegaba RGB blanco sobre blanco → imagen
    toda blanca → _dhash todo ceros → el dedup rechazaba todo.
    """
    from PIL import Image

    from core.inkcore.bank import _dhash
    p = tmp_path / "ell.png"
    assert _make_alpha_glyph(p, "ellipse")
    h = _dhash(Image.open(p).convert("RGBA"))
    assert set(h) != {"0"}, "el hash colapsó a todo ceros (bug del dedup)"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_distinct_alpha_glyphs_accepted(bank, tmp_path):
    """Dos muestras VISUALMENTE distintas del mismo char deben aceptarse ambas.

    Antes del fix la segunda se rechazaba con hamming=0 (todos los hashes eran
    iguales), impidiendo acumular muestras en el banco.
    """
    p1, p2 = tmp_path / "g1.png", tmp_path / "g2.png"
    if not _make_alpha_glyph(p1, "ellipse"):
        pytest.skip("PIL not available")
    _make_alpha_glyph(p2, "rect")
    r1 = bank.add_glyph("a", str(p1))
    r2 = bank.add_glyph("a", str(p2))
    assert r1 is not None
    assert r2 is not None
    assert len(bank.get_all(char_filter="a")) == 2


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_backfill_recomputes_degenerate_hash(bank, tmp_path):
    """Un hash degenerado ('000…0') guardado por el _dhash roto debe sanearse al load."""
    p = tmp_path / "g.png"
    if not _make_alpha_glyph(p, "ellipse"):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("a", str(p))
    assert entry is not None
    entry.perceptual_hash = "0" * 256
    bank.save()
    from core.inkcore.bank import GlyphBank
    bank2 = GlyphBank()
    e2 = bank2.get_all(char_filter="a")[0]
    assert set(e2.perceptual_hash) != {"0"}, "el backfill no recomputó el hash degenerado"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_glyph_to_gray_prefiere_canal_con_senal(tmp_path):
    """Glifo del extractor SIN fondo transparente (alpha alto pero con forma).

    Regresión del criterio viejo (alpha.min() < 250 → usa alpha, si no luminancia):
    un glifo con alpha denso caía en la rama de luminancia y, como su RGB es blanco
    uniforme, daba presencia 0 → hash degenerado. Ahora se elige el canal con mayor
    rango dinámico, así que la forma sutil del alpha se conserva.
    """
    import numpy as np
    from PIL import Image

    from core.inkcore.bank import GlyphBank, _dhash
    arr = np.full((48, 48, 4), 255, dtype=np.uint8)  # RGB y alpha altos uniformes
    arr[12:36, 12:36, 3] = 252                        # forma sutil SOLO en el alpha
    h = _dhash(Image.fromarray(arr))
    assert not GlyphBank._is_degenerate_hash(h), "colapsó pese a tener forma en alpha"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_dedup_robusto_con_basura_degenerada(bank, tmp_path):
    """Dos glifos planos DISTINTOS (ambos sin señal perceptual) no deben rechazarse.

    Reproduce el corazón del bug: cuando todos los hashes colapsaban a '000…0',
    glifos visualmente distintos daban hamming=0 entre sí ⇒ se rechazaban como
    duplicados. El dedup ahora ignora los hashes degenerados en vez de tratar la
    basura como duplicado universal, así que ambas muestras entran.
    """
    from PIL import Image
    p1, p2 = tmp_path / "black.png", tmp_path / "white.png"
    try:
        Image.new("RGBA", (24, 24), (0, 0, 0, 255)).save(p1)     # negro sólido
        Image.new("RGBA", (24, 24), (255, 255, 255, 255)).save(p2)  # blanco sólido
    except Exception:
        pytest.skip("PIL not available")
    e1 = bank.add_glyph("z", str(p1))
    e2 = bank.add_glyph("z", str(p2))
    assert e1 is not None and e2 is not None, "glifos distintos rechazados por hash degenerado"
    assert len(bank.get_all(char_filter="z")) == 2


def test_purge_temp_pngs_descarta_huerfanos(tmp_path):
    """purge_temp_pngs borra solo los PNG huérfanos, deja intactos otros archivos."""
    from core.inkcore.glyph_ingest import purge_temp_pngs
    for i in range(3):
        (tmp_path / f"orphan_{i}.png").write_bytes(b"\x89PNG")
    (tmp_path / "keep.json").write_bytes(b"{}")
    removed = purge_temp_pngs(tmp_path)
    assert removed == 3
    assert not list(tmp_path.glob("*.png"))
    assert (tmp_path / "keep.json").exists()


def test_coverage_empty(bank):
    cov = bank.coverage()
    assert cov["total_glyphs"] == 0
    assert cov["unique_chars"] == 0


def test_bank_manifest_written(bank, tmp_path):
    import config
    # v4.2: el manifest vive en tipografia/{profile_id}/_manifest.json
    manifest = config.TIPOGRAFIA_DIR / config.DEFAULT_PROFILE_ID / "_manifest.json"
    assert manifest.exists()
