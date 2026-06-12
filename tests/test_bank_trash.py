"""Tests de la papelera del banco de glifos (core/inkcore/bank_trash.py).

Mismos patrones que test_bank.py: fixture ``bank`` sobre el DATA_DIR temporal
(conftest redirige TIPOGRAFIA_DIR a tmp_path) y glifos estilo-extractor con la
forma en el canal alpha, generados con PIL.
"""
import json
from pathlib import Path

import pytest

from core.inkcore.bank_trash import empty_trash, list_trash, restore_trash, trash_glyphs

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)


def _make_alpha_glyph(path: Path, shape: str = "ellipse", px: int = 48) -> bool:
    """Glifo estilo-extractor: RGB blanco, forma codificada en el canal alpha."""
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


@pytest.fixture
def bank(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    return GlyphBank()


def _add_glyphs(bank, tmp_path, specs):
    """Agrega glifos al banco. specs = [(char, shape), ...]. Devuelve los entries."""
    entries = []
    for i, (char, shape) in enumerate(specs):
        src = tmp_path / f"src_{char}_{i}.png"
        if not _make_alpha_glyph(src, shape):
            pytest.skip("PIL not available")
        entry = bank.add_glyph(char, str(src))
        assert entry is not None
        entries.append(entry)
    return entries


def test_trash_mueve_archivos_y_quita_del_banco(bank, tmp_path):
    """trash_glyphs mueve los PNG a .trash/{id}/ y quita las entradas del banco."""
    entries = _add_glyphs(bank, tmp_path, [("a", "ellipse"), ("b", "rect")])
    old_paths = [Path(e.image_path) for e in entries]

    trash_id = trash_glyphs(bank, entries)
    assert trash_id is not None

    # Fuera del banco (memoria y manifest persistido)
    assert bank.get_all() == []
    from core.inkcore.bank import GlyphBank
    assert GlyphBank().get_all() == []

    # Los PNG ya no están en bank_dir: se MOVIERON (no copiaron) a la papelera
    for p in old_paths:
        assert not p.exists()
    trash_dir = bank.bank_dir / ".trash" / trash_id
    assert trash_dir.is_dir()
    assert len(list(trash_dir.glob("*.png"))) == 2

    # El manifest de la papelera serializa las entradas completas
    data = json.loads((trash_dir / "manifest.json").read_text(encoding="utf-8"))
    assert {d["char"] for d in data["entries"]} == {"a", "b"}
    assert all(d.get("_trash_file") for d in data["entries"])


def test_restore_devuelve_glifos_y_limpia_papelera(bank, tmp_path):
    """restore_trash re-agrega los glifos (mismo char/tier/score) y borra la papelera."""
    entries = _add_glyphs(bank, tmp_path, [("a", "ellipse"), ("b", "rect")])
    before = {e.char: (e.tier, e.quality_score) for e in entries}

    trash_id = trash_glyphs(bank, entries)
    assert bank.get_all() == []

    restored = restore_trash(bank, trash_id)
    assert restored == 2

    # De vuelta en el banco con el mismo char y tier (score preservado vía
    # quality_override, sin recalcular)
    for char, (tier, score) in before.items():
        got = bank.get_all(char_filter=char)
        assert len(got) == 1
        assert got[0].tier == tier
        assert got[0].quality_score == pytest.approx(score)
        assert Path(got[0].image_path).exists()

    # Persistido: un banco recargado también los ve
    from core.inkcore.bank import GlyphBank
    assert len(GlyphBank().get_all()) == 2

    # La papelera quedó eliminada
    assert not (bank.bank_dir / ".trash" / trash_id).exists()
    assert list_trash(bank.bank_dir) == []


def test_restore_papelera_inexistente_devuelve_cero(bank):
    assert restore_trash(bank, "no-existe") == 0


def test_list_trash_reporta_id_timestamp_y_count(bank, tmp_path):
    e1 = _add_glyphs(bank, tmp_path, [("a", "ellipse")])
    id1 = trash_glyphs(bank, e1)
    e2 = _add_glyphs(bank, tmp_path, [("b", "rect"), ("c", "line")])
    id2 = trash_glyphs(bank, e2)

    listado = list_trash(bank.bank_dir)
    assert {t["id"] for t in listado} == {id1, id2}
    by_id = {t["id"]: t for t in listado}
    assert by_id[id1]["count"] == 1
    assert by_id[id2]["count"] == 2
    assert all(isinstance(t["timestamp"], float) and t["timestamp"] > 0 for t in listado)
    # Orden: más reciente primero
    assert listado[0]["id"] == id2


def test_empty_trash_borra_todas(bank, tmp_path):
    for char, shape in [("a", "ellipse"), ("b", "rect")]:
        trash_glyphs(bank, _add_glyphs(bank, tmp_path, [(char, shape)]))
    assert len(list_trash(bank.bank_dir)) == 2

    assert empty_trash(bank.bank_dir) == 2
    assert list_trash(bank.bank_dir) == []
    # Idempotente: sin papeleras no borra nada
    assert empty_trash(bank.bank_dir) == 0


def test_empty_trash_respeta_older_than(bank, tmp_path):
    trash_glyphs(bank, _add_glyphs(bank, tmp_path, [("a", "ellipse")]))
    # Recién creada: con umbral de 1 hora no debe borrarse
    assert empty_trash(bank.bank_dir, older_than_s=3600.0) == 0
    assert len(list_trash(bank.bank_dir)) == 1
    # Con umbral 0 (todo es "más viejo que 0s") sí se borra
    assert empty_trash(bank.bank_dir, older_than_s=0.0) == 1
    assert list_trash(bank.bank_dir) == []


def test_trash_lista_vacia_devuelve_none(bank):
    assert trash_glyphs(bank, []) is None
    # No deja basura: ni siquiera se creó el directorio .trash/
    assert not (bank.bank_dir / ".trash").exists()
    assert list_trash(bank.bank_dir) == []
