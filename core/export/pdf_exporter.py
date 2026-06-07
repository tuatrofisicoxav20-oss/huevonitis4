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
    """Pega lista de imágenes RGB (de renderer.render_pages) como páginas A4 de un PDF.

    Cierra el flujo: OCR → reescribir con mi letra → exportar PDF.
    """
    if not PIL_OK or not RL_OK:
        return False
    if not images:
        return False

    tmp_files: list[str] = []
    try:
        c = rl_canvas.Canvas(output_path, pagesize=A4)
        pw, ph = A4
        margin = 1.5 * cm

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
