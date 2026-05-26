"""A10: tests de regresión para el cache key con backend + opciones."""
import pickle
from unittest.mock import patch


def _make_fake_doc(text: str = "hello"):
    """Crea un Document mínimo pickleable."""
    from core.ocr.document_model import Document
    doc = Document(source_path="/fake/path.png", source_type="image")
    return doc


def test_cache_key_diferente_por_backend(tmp_path):
    """Documentos procesados con distinto backend NO comparten entrada de caché."""
    with patch("config.OCR_CACHE_DIR", tmp_path):
        from core.ocr.result_cache import _cache_key

        # Mismo archivo, misma firma de opciones, backends distintos
        src = tmp_path / "fake.png"
        src.write_bytes(b"")

        key_a = _cache_key(str(src), "tesseract", "spa|200|0|all|1")
        key_b = _cache_key(str(src), "paddleocr", "spa|200|0|all|1")
        assert key_a != key_b, "Keys distintos backends deben diferir"


def test_cache_key_diferente_por_opciones(tmp_path):
    """Documentos procesados con distintas opciones NO comparten entrada."""
    with patch("config.OCR_CACHE_DIR", tmp_path):
        from core.ocr.result_cache import _cache_key

        src = tmp_path / "fake.png"
        src.write_bytes(b"")

        key_a = _cache_key(str(src), "tesseract", "spa|200|0|all|1")
        key_b = _cache_key(str(src), "tesseract", "eng|200|0|all|1")
        assert key_a != key_b, "Keys con distinto lang deben diferir"


def test_cache_no_reutiliza_entre_backends(tmp_path):
    """get() con backend B NO devuelve resultado guardado con backend A."""
    with patch("config.OCR_CACHE_DIR", tmp_path):
        from core.ocr.result_cache import OCRResultCache

        src = tmp_path / "sample.png"
        src.write_bytes(b"\x89PNG")

        doc_a = _make_fake_doc("resultado de tesseract")
        cache = OCRResultCache()
        cache.put(str(src), doc_a, "tesseract", "spa|200|0|all|1")

        # Leer con backend diferente debe devolver None
        result = cache.get(str(src), "paddleocr", "spa|200|0|all|1")
        assert result is None, "Caché no debe cruzar entre backends"

        # Leer con el mismo backend debe devolver el documento
        result2 = cache.get(str(src), "tesseract", "spa|200|0|all|1")
        assert result2 is not None, "Mismo backend debe encontrar la entrada"


def test_options_signature_deterministica():
    """OCROptions.signature() debe ser estable e independiente de use_cache."""
    from core.ocr.options import OCROptions

    opts1 = OCROptions(lang="spa", pdf_dpi=200, detect_handwriting=False,
                       pdf_pages=None, preserve_layout=True,
                       use_cache=True, parallel_pages=1)
    opts2 = OCROptions(lang="spa", pdf_dpi=200, detect_handwriting=False,
                       pdf_pages=None, preserve_layout=True,
                       use_cache=False, parallel_pages=4)  # distintos, no afectan resultado

    assert opts1.signature() == opts2.signature(), \
        "use_cache y parallel_pages no deben afectar la firma"


def test_options_signature_cambia_con_dpi():
    from core.ocr.options import OCROptions

    opts_lo = OCROptions(pdf_dpi=150)
    opts_hi = OCROptions(pdf_dpi=300)
    assert opts_lo.signature() != opts_hi.signature()


def test_cache_migration_limpia_v1(tmp_path):
    """Al inicializar con caché de versión anterior, se limpian las entradas viejas."""
    with patch("config.OCR_CACHE_DIR", tmp_path):
        # Simular entrada v1 sin archivo de versión
        fake_pkl = tmp_path / "aabbcc.pkl"
        fake_pkl.write_bytes(pickle.dumps({"old": True}))
        assert fake_pkl.exists()

        from core.ocr.result_cache import OCRResultCache
        _ = OCRResultCache()  # debe migrar y borrar

        assert not fake_pkl.exists(), "Migración debe borrar entradas v1"
        assert (tmp_path / ".cache_version").read_text().strip() == "2"
