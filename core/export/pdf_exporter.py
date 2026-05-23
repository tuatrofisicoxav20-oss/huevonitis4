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


def export_document_pdf(doc: "object", output_path: str, title: str | None = None) -> bool:
    """Exporta un Document estructurado a PDF con estilos por block_type.

    HEADING → Heading{level}, LIST_ITEM → bullet + indent, CODE → Courier en
    cuadro gris. Mantiene export_text_pdf para compat con callers existentes.
    """
    if not RL_OK:
        logger.error("reportlab not available")
        return False
    try:
        from core.ocr.document_model import BlockType
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        doc_pdf = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm, leftMargin=2 * cm,
            topMargin=2 * cm, bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()

        h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
        h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceAfter=6)
        h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11, spaceAfter=4)
        body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=11, leading=16, spaceAfter=6)
        bullet_style = ParagraphStyle("Bullet", parent=body, leftIndent=20, bulletIndent=10, spaceAfter=4)
        code_style = ParagraphStyle(
            "Code", parent=styles["Normal"],
            fontName="Courier", fontSize=9, leading=13,
            backColor="#F0F0F0", leftIndent=12, rightIndent=12,
            spaceAfter=6, spaceBefore=4,
        )

        story = []
        if title:
            story.append(Paragraph(title, styles["Title"]))
            story.append(Spacer(1, 0.3 * cm))

        def _safe(t: str) -> str:
            return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        for page in doc.pages:
            for block in page.blocks:
                text = block.text.strip()
                if not text:
                    continue
                lvl = getattr(block, "heading_level", 1) or 1
                btype = block.block_type

                if btype == BlockType.HEADING:
                    st = h1 if lvl == 1 else h2 if lvl == 2 else h3
                    story.append(Paragraph(_safe(text), st))
                elif btype == BlockType.LIST_ITEM:
                    story.append(Paragraph(f"• {_safe(text)}", bullet_style))
                elif btype == BlockType.CODE:
                    story.append(Paragraph(_safe(text), code_style))
                else:
                    story.append(Paragraph(_safe(text), body))

        doc_pdf.build(story)
        return True
    except Exception as exc:
        logger.error("export_document_pdf error: %s", exc)
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

    import tempfile
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


def export_image_pdf(image, output_path: str) -> bool:
    if not PIL_OK or not RL_OK:
        return False
    if not hasattr(image, 'save'):
        return False
    tmp_file = None
    try:
        if getattr(image, 'mode', None) == 'RGBA':
            background = PILImage.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel('A'))
            save_image = background
        else:
            save_image = image.convert("RGB") if getattr(image, 'mode', None) != 'RGB' else image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp_file = tf.name
        save_image.save(tmp_file)
        c = rl_canvas.Canvas(output_path, pagesize=A4)
        pw, ph = A4
        margin = 2 * cm
        c.drawImage(tmp_file, margin, margin,
                    width=pw - 2 * margin, height=ph - 2 * margin,
                    preserveAspectRatio=True)
        c.save()
        return True
    except Exception as e:
        logger.error(f"Image PDF export error: {e}")
        return False
    finally:
        if tmp_file:
            Path(tmp_file).unlink(missing_ok=True)
