import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.enums import TA_LEFT
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


def export_image_pdf(image, output_path: str) -> bool:
    if not PIL_OK or not RL_OK:
        return False
    if not hasattr(image, 'save'):
        return False
    temp_path = str(output_path).replace(".pdf", "_tmp.png")
    try:
        # Bug fix #8: ReportLab does not natively handle RGBA images when
        # rendering to PDF — the alpha channel produces unexpected results.
        # Flatten to RGB over a white background before saving the temp file.
        if getattr(image, 'mode', None) == 'RGBA':
            background = PILImage.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel('A'))
            save_image = background
        else:
            save_image = image.convert("RGB") if getattr(image, 'mode', None) != 'RGB' else image
        save_image.save(temp_path)
        c = rl_canvas.Canvas(output_path, pagesize=A4)
        w, h = A4
        c.drawImage(temp_path, 0, 0, width=w, height=h, preserveAspectRatio=True)
        c.save()
        return True
    except Exception as e:
        logger.error(f"Image PDF export error: {e}")
        return False
    finally:
        # Bug fix #9: always clean up the temp file, even if c.save() raised
        Path(temp_path).unlink(missing_ok=True)
