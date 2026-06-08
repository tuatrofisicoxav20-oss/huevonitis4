"""Tests de GlyphBank.auto_curate: demote por mal-clasificación del CNN.

Se usa un clasificador STUB (determinista) para no depender del modelo entrenado:
puntúa cada glifo según el tamaño de su imagen, así controlamos qué se considera
bien/mal clasificado sin latencia ni descargas.
"""
import numpy as np
import pytest
from PIL import Image

from core.inkcore.bank import GlyphBank
from core.models import GlyphEntry


def _write_glyph(path, size):
    """Glifo RGBA con la forma en el alpha (como los del extractor)."""
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[3:size - 3, 3:size - 3, 3] = 255
    Image.fromarray(arr).save(path)


class _StubCNN:
    """score()/predict_topk() decididos por la altura del mask.

    Convención del test: altura 31 ⇒ "mal clasificado" (score bajo, top 'x');
    cualquier otra altura ⇒ "bien clasificado" (score alto, top = la esperada).
    """
    available = True

    def score(self, mask, expected_char):
        return 0.01 if mask.shape[0] == 31 else 0.90

    def predict_topk(self, mask, k=1):
        if mask.shape[0] == 31:
            return [("x", 0.80)]
        return [("a", 0.90)]  # top "correcto" simbólico; auto_curate sólo mira mismatch


def _add(bank, char, fname, size, tier="Gold"):
    p = bank.bank_dir / fname
    _write_glyph(p, size)
    e = GlyphEntry(char=char, image_path=str(p), tier=tier, quality_score=0.9)
    bank._entries.append(e)
    return e


@pytest.fixture
def bank():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    return GlyphBank()


def test_demote_mal_clasificado_conserva_buenos(bank):
    """Un glifo que el CNN ve como OTRA letra pasa a Bronze; los buenos quedan."""
    _add(bank, "a", "a_good1.png", 30)
    _add(bank, "a", "a_good2.png", 32)
    bad = _add(bank, "a", "a_bad.png", 31)   # mask 31 ⇒ mal clasificado
    bank._rebuild_indices()

    stats = bank.auto_curate(classifier=_StubCNN())

    assert stats["available"] is True
    assert stats["demoted"] == 1
    assert stats["by_char"].get("a") == 1
    assert bad.tier == "Bronze"
    golds = [e for e in bank._by_char["a"] if e.tier == "Gold"]
    assert len(golds) == 2


def test_nunca_vacia_un_caracter(bank):
    """Si todos parecen malos, se conserva igual el mejor (no se vacía la letra)."""
    _add(bank, "b", "b_bad1.png", 31)
    _add(bank, "b", "b_bad2.png", 31)
    bank._rebuild_indices()

    stats = bank.auto_curate(classifier=_StubCNN())

    # 2 malos, pero el "mejor" queda protegido ⇒ sólo 1 demovido.
    assert stats["demoted"] == 1
    rotation = [e for e in bank._by_char["b"] if e.tier in ("Gold", "Silver")]
    assert len(rotation) == 1


def test_un_solo_glifo_no_se_toca(bank):
    """Con un único glifo en rotación no se demueve (no se puede sin vaciar)."""
    e = _add(bank, "c", "c_bad.png", 31)
    bank._rebuild_indices()
    stats = bank.auto_curate(classifier=_StubCNN())
    assert stats["demoted"] == 0
    assert e.tier == "Gold"


def test_enie_y_digitos_se_ignoran(bank):
    """ñ y dígitos no existen en EMNIST: auto_curate no los toca."""
    e1 = _add(bank, "ñ", "enie1.png", 31)
    _add(bank, "ñ", "enie2.png", 30)
    bank._rebuild_indices()
    stats = bank.auto_curate(classifier=_StubCNN())
    assert stats["demoted"] == 0
    assert e1.tier == "Gold"


def test_sin_modelo_es_noop(bank):
    """Clasificador no disponible ⇒ no-op seguro."""
    _add(bank, "a", "a1.png", 31)
    _add(bank, "a", "a2.png", 30)
    bank._rebuild_indices()

    class _Unavail:
        available = False

    stats = bank.auto_curate(classifier=_Unavail())
    assert stats["available"] is False
    assert stats["demoted"] == 0
