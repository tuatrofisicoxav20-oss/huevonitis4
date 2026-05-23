"""Helper compartido: aplica TESSERACT_CMD desde config en ambos lados
(TesseractBackend y TesseractLabeler) para evitar duplicación."""
import logging

logger = logging.getLogger(__name__)

try:
    import pytesseract as _pytesseract
    _OK = True
except ImportError:
    _OK = False


def apply_tesseract_cmd() -> None:
    """Aplica config.TESSERACT_CMD a pytesseract si está configurado."""
    if not _OK:
        return
    try:
        import config
        if config.TESSERACT_CMD:
            _pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    except Exception as exc:
        logger.debug("apply_tesseract_cmd: %s", exc)
