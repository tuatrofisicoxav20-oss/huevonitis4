import contextlib
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    RL_OK = True
except ImportError:
    RL_OK = False

try:
    from PIL import Image as PILImage
    PIL_OK = True
except ImportError:
    PIL_OK = False


def export_text_pdf(text: str, output_path: str, title: str = "Documento") -> bool:
    if not RL_OK:
        logger.error("reportlab not available")
        return False
    try:
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=11,
            leading=16,
            spaceAfter=8,
        )
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=16,
            spaceAfter=16,
        )
        story = [Paragraph(title, title_style), Spacer(1, 0.3*cm)]
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                safe = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, body_style))
        doc.build(story)
        return True
    except Exception as e:
        logger.error(f"PDF export error: {e}")
        return False


def export_rendered_pages_pdf(
    images: "list",
    output_path: str,
    title: str | None = None,
) -> bool:
    """Pega lista de imágenes RGB (de renderer.render_pages) como páginas CARTA de un PDF.

    Cada imagen ocupa la página COMPLETA, sin margen del PDF: el render ya trae
    sus márgenes físicos en mm y un margen extra correría el texto, desfasando
    el interlineado de los renglones de la hoja impresa. Una página de render
    carta a 150 DPI (1275×1650 px) mapea 1:1 a los 612×792 pt del PDF carta.
    Cierra el flujo: texto → reescribir con mi letra → PDF imprimible.
    """
    if not PIL_OK or not RL_OK:
        return False
    if not images:
        return False

    from reportlab.lib.pagesizes import letter as RL_LETTER

    tmp_files: list[str] = []
    try:
        c = rl_canvas.Canvas(output_path, pagesize=RL_LETTER)
        pw, ph = RL_LETTER
        margin = 0.0

        for i, img in enumerate(images):
            if getattr(img, "mode", None) == "RGBA":
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.getchannel("A"))
                save_img = bg
            elif getattr(img, "mode", None) != "RGB":
                save_img = img.convert("RGB")
            else:
                save_img = img

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp_path = tf.name
            tmp_files.append(tmp_path)
            save_img.save(tmp_path)

            if i > 0:
                c.showPage()
            c.drawImage(
                tmp_path, margin, margin,
                width=pw - 2 * margin, height=ph - 2 * margin,
                preserveAspectRatio=True, anchor="nw",
            )

        c.save()
        return True
    except Exception as exc:
        logger.error("export_rendered_pages_pdf error: %s", exc)
        return False
    finally:
        for p in tmp_files:
            Path(p).unlink(missing_ok=True)


def export_pages_streaming(
    pages,
    output_path: str,
    *,
    page_size: str = "letter",
    margin_cm: float = 0.0,
    progress_cb=None,
    total: "int | None" = None,
) -> bool:
    """Exporta un PDF consumiendo un ITERADOR de páginas, con RAM constante.

    A diferencia de export_rendered_pages_pdf (que recibe la lista entera), acá
    ``pages`` puede ser un generador (renderer.iter_pages): se escribe cada página
    al PDF y se libera ANTES de pedir la siguiente, así el pico de RAM es plano sin
    importar cuántas páginas haya (clave para 36+ páginas en 16GB). No usa archivos
    temporales: cada página va a un buffer en memoria que se descarta enseguida.

    page_size: "letter" (carta 8.5×11") o "a4". margin_cm: margen del PDF —
    default 0: el render ya trae sus márgenes físicos en mm, y un margen extra
    correría el texto y desfasaría el interlineado de los renglones de la hoja
    impresa (la imagen debe ocupar la página completa para que 1 px del render
    caiga en su posición física exacta).
    progress_cb(actual, total): callback opcional para la barra de progreso.
    Devuelve False si no se escribió ninguna página.
    """
    if not PIL_OK or not RL_OK:
        logger.error("export_pages_streaming: faltan PIL/reportlab")
        return False
    import io

    from reportlab.lib.pagesizes import A4 as RL_A4
    from reportlab.lib.pagesizes import letter as RL_LETTER
    from reportlab.lib.utils import ImageReader

    psize = RL_A4 if str(page_size).lower() == "a4" else RL_LETTER
    pw, ph = psize
    margin = margin_cm * cm
    c = rl_canvas.Canvas(output_path, pagesize=psize)
    n = 0
    try:
        for img in pages:
            if getattr(img, "mode", None) == "RGBA":
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.getchannel("A"))
                save_img = bg
            elif getattr(img, "mode", None) != "RGB":
                save_img = img.convert("RGB")
            else:
                save_img = img
            buf = io.BytesIO()
            save_img.save(buf, format="PNG")
            buf.seek(0)
            if n > 0:
                c.showPage()
            c.drawImage(
                ImageReader(buf), margin, margin,
                width=pw - 2 * margin, height=ph - 2 * margin,
                preserveAspectRatio=True, anchor="nw",
            )
            n += 1
            if progress_cb is not None:
                # un callback de UI no debe tumbar el export
                with contextlib.suppress(Exception):
                    progress_cb(n, total)
            buf.close()
            save_img = None  # liberar antes de la próxima página
        if n == 0:
            return False
        c.save()
        return True
    except Exception as exc:
        logger.error("export_pages_streaming error: %s", exc)
        return False
