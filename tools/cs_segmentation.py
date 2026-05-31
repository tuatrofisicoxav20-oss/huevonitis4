"""
Comparación de estrategias de segmentación de caracteres (flujo legacy).

Calcula y reporta las métricas de cada estrategia de segmentación del
extractor sobre la primera línea detectada de la imagen. Si no se provee
texto de referencia, intenta estimarlo con Tesseract.
"""
import os
import sys

# Agregar el directorio raíz de la app al path
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    print("ERROR: cv2 no disponible. Instalar con: pip install opencv-python")
    sys.exit(1)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    print("ERROR: Pillow no disponible. Instalar con: pip install Pillow")
    sys.exit(1)

try:
    import pytesseract
    TESS_OK = True
except ImportError:
    TESS_OK = False
    print("ADVERTENCIA: pytesseract no disponible — texto de referencia debe proveerse manualmente")

from core.inkcore.extractor import ExtractionOptions, GlyphExtractor  # noqa: E402


def get_reference_text_from_tesseract(line_mask: np.ndarray) -> str:
    """Intenta extraer texto de la primera línea con Tesseract."""
    if not TESS_OK:
        return ""
    try:
        h, w = line_mask.shape[:2]
        target_h = max(200, h * 3)
        scale = target_h / max(1, h)
        scaled_w = int(w * scale)
        lm = cv2.resize(line_mask, (scaled_w, target_h), interpolation=cv2.INTER_LINEAR)
        _, lm = cv2.threshold(lm, 127, 255, cv2.THRESH_BINARY)
        border = 50
        lm = cv2.copyMakeBorder(lm, border, border, border, border,
                                 cv2.BORDER_CONSTANT, value=0)
        tess_in = 255 - lm
        pil_in = Image.fromarray(tess_in, mode="L")
        text = pytesseract.image_to_string(pil_in, lang="spa",
                                            config="--psm 7 --oem 3").strip()
        return "".join(c for c in text if c not in " \n\t")
    except Exception as e:
        print(f"  Tesseract OCR falló: {e}")
        return ""


def run_comparison(image_path: str, ref_text: str = "") -> None:
    print(f"\n{'='*70}")
    print("  COMPARACIÓN DE ESTRATEGIAS DE SEGMENTACIÓN")
    print(f"  Imagen: {os.path.basename(image_path)}")
    print(f"{'='*70}\n")

    if not os.path.exists(image_path):
        print(f"ERROR: imagen no encontrada: {image_path}")
        return

    extractor = GlyphExtractor()
    opts = ExtractionOptions()

    # Cargar y preprocesar
    print("Cargando y preprocesando imagen...")
    img = cv2.imread(image_path)
    if img is None:
        print("ERROR: no se pudo cargar la imagen")
        return

    img = extractor._apply_manual(img, opts)
    img = extractor._scale(img)
    img = extractor._autocrop(img)
    img, skew = extractor._deskew(img)
    if abs(skew) > 0.3:
        print(f"  Inclinación corregida: {skew:.2f}°")

    gray, raw_mask, clean = extractor._full_preprocess(img, opts)

    # Detectar líneas
    print("Detectando líneas de texto...")
    line_boxes = extractor._find_line_boxes(clean)
    if not line_boxes:
        print("ERROR: no se detectaron líneas de texto")
        return

    print(f"  {len(line_boxes)} línea(s) detectada(s)")
    for i, lb in enumerate(line_boxes):
        print(f"    Línea {i}: x={lb.x} y={lb.y} w={lb.w} h={lb.h}")

    # Usar la primera línea
    lb = line_boxes[0]
    lx, ly = lb.x, lb.y
    line_mask = clean[ly:ly + lb.h, lx:lx + lb.w]

    if line_mask.size == 0 or not np.any(line_mask > 0):
        print("ERROR: máscara de la primera línea vacía")
        return

    # Texto de referencia
    if not ref_text:
        print("\nObteniendo texto de referencia con Tesseract...")
        ref_text = get_reference_text_from_tesseract(line_mask)
        if ref_text:
            print(f"  Tesseract detectó: '{ref_text}'")
        else:
            # Fallback: estimar número de chars por ancho de banda
            char_w_estimate = max(10, lb.h)
            n_estimate = max(1, int(lb.w / char_w_estimate))
            ref_text = "a" * n_estimate
            print(f"  Sin OCR — usando {n_estimate} caracteres de relleno ('a'×{n_estimate})")

    chars = [c for c in ref_text if c != " "]
    if not chars:
        print("ERROR: texto de referencia vacío o solo espacios")
        return

    n = len(chars)
    print(f"\nTexto de referencia: '{ref_text}' ({n} caracteres)")

    # Calcular x_min / x_max de la banda
    vpp = np.sum(line_mask > 0, axis=0).astype(np.float32)
    ink_cols = np.where(vpp > 0)[0]
    if len(ink_cols) == 0:
        print("ERROR: banda sin tinta")
        return
    p2 = max(0, int(len(ink_cols) * 0.02))
    p98 = min(len(ink_cols) - 1, int(len(ink_cols) * 0.98))
    x_min = int(ink_cols[p2])
    x_max = int(ink_cols[p98]) + 1

    print(f"  Span tinta: x={x_min}..{x_max} ({x_max - x_min}px)")
    print(f"  Ancho promedio por char: {(x_max - x_min) / n:.1f}px")

    # Ejecutar comparación
    print("\nEjecutando todas las estrategias...")
    results = extractor._test_all_strategies(
        band_img=line_mask,
        band_binary=line_mask,
        x_min=x_min,
        x_max=x_max,
        n=n,
        chars=chars,
        line_mask=line_mask,
    )

    if not results:
        print("ERROR: _test_all_strategies devolvió resultado vacío")
        return

    # Imprimir tabla de resultados
    print(f"\n{'─'*70}")
    print(f"{'Estrategia':<38} {'Glifos':>6} {'Avg Q':>7} {'Min Q':>7} {'Max Q':>7}")
    print(f"{'─'*70}")

    best_name = ""
    best_score = -1.0

    for name, r in results.items():
        if "error" in r:
            print(f"{name:<38} {'ERROR':>6}  {r['error'][:28]}")
            continue
        gc = r.get("glyph_count", 0)
        avg = r.get("avg_quality", 0.0)
        mn = r.get("min_quality", 0.0)
        mx = r.get("max_quality", 0.0)
        note = r.get("note", "")
        if note:
            print(f"{name:<38} {note:>28}")
            continue
        # Puntuación combinada: priorizar glifos completos + calidad promedio
        combined = avg * 0.7 + (gc / max(1, n)) * 0.3
        if combined > best_score:
            best_score = combined
            best_name = name
        print(f"{name:<38} {gc:>6}  {avg:>7.3f}  {mn:>7.3f}  {mx:>7.3f}")

    print(f"{'─'*70}")
    print(f"\nMejor estrategia: [{best_name}]  (score combinado: {best_score:.3f})")

    # Detalle de fronteras de la mejor estrategia
    if best_name in results and "boundaries" in results[best_name]:
        bounds = results[best_name]["boundaries"]
        print(f"  Fronteras: {bounds[:10]}{'...' if len(bounds) > 10 else ''}")

    print(f"\n{'='*70}\n")
