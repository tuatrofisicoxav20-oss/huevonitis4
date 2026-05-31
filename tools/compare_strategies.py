"""
Herramienta de comparación de estrategias de segmentación de caracteres.

Uso:
    python tools/compare_strategies.py <ruta_imagen> [texto_referencia]

Si no se proporciona texto de referencia, se intenta usar Tesseract para
obtener una estimación del texto de la primera línea.

Este módulo es el punto de entrada CLI. La lógica está repartida en:
  - tools/cs_segmentation.py : comparación de estrategias de segmentación (legacy).
  - tools/cs_ensemble.py     : comparación de backends OCR y pipeline ensemble.
  - tools/cs_report.py       : render del informe HTML.
"""
import logging
import os
import sys

# Agregar el directorio raíz de la app al path
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

logging.basicConfig(level=logging.WARNING)  # suprimir logs de producción durante prueba


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Comparación de estrategias de extracción de glifos"
    )
    parser.add_argument("image", help="Ruta a la imagen")
    parser.add_argument("ref_text", nargs="?", default="",
                        help="Texto de referencia (para modo legacy)")
    parser.add_argument("--ocr", action="store_true",
                        help="Comparar backends OCR en vez de estrategias de segmentación")
    parser.add_argument("--strategies",
                        default="legacy,classic_only,ensemble_all",
                        help="Estrategias separadas por coma "
                             "(legacy,classic_only,craft_only,paddle_only,"
                             "ensemble_all,union,intersection,cascade)")
    parser.add_argument("--labelers", default="",
                        help="Labelers separados por coma (tesseract_labeler,trocr_labeler)")
    parser.add_argument("--output", default=None,
                        help="Ruta del informe HTML de salida")

    args = parser.parse_args()

    if args.ocr:
        from tools.cs_ensemble import run_ocr_comparison
        run_ocr_comparison(args.image)
    elif args.strategies and args.strategies != "segmentation":
        from tools.cs_ensemble import run_ensemble_comparison
        strats = [s.strip() for s in args.strategies.split(",") if s.strip()]
        labelers = [l.strip() for l in args.labelers.split(",") if l.strip()]
        run_ensemble_comparison(args.image, strats, labelers, args.output)
    else:
        from tools.cs_segmentation import run_comparison
        run_comparison(args.image, args.ref_text)


if __name__ == "__main__":
    main()
