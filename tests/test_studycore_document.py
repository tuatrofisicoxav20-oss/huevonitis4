"""D2: build_study_bundle_from_document usa jerarquía del Document."""
from core.ocr.document_model import BlockType, Document, DocumentPage, TextBlock
from core.studycore.builder import build_study_bundle_from_document


def _make_doc():
    doc = Document(source_path="/tmp/fake.pdf", source_type="text_pdf")
    page = DocumentPage(page_number=1)
    page.blocks = [
        TextBlock(text="Fotosíntesis", block_type=BlockType.HEADING, heading_level=1),
        TextBlock(
            text="Proceso por el cual las plantas convierten luz solar en energía química.",
            block_type=BlockType.PARAGRAPH,
        ),
        TextBlock(text="Respiración celular", block_type=BlockType.HEADING, heading_level=1),
        TextBlock(
            text="Proceso metabólico que convierte glucosa en ATP.",
            block_type=BlockType.PARAGRAPH,
        ),
        TextBlock(text="La mitocondria es el organelo donde ocurre la respiración.", block_type=BlockType.PARAGRAPH),
    ]
    doc.pages.append(page)
    return doc


def test_flashcards_from_headings():
    doc = _make_doc()
    bundle = build_study_bundle_from_document(doc)
    questions = [fc.question for fc in bundle.flashcards]
    assert any("Fotosíntesis" in q for q in questions), f"flashcards: {questions}"
    assert any("Respiración" in q for q in questions), f"flashcards: {questions}"


def test_key_terms_include_headings():
    doc = _make_doc()
    bundle = build_study_bundle_from_document(doc)
    # Los headings deben aparecer primero en key_terms
    assert "Fotosíntesis" in bundle.key_terms or "fotosíntesis" in [t.lower() for t in bundle.key_terms]


def test_bundle_has_summary_and_quiz():
    doc = _make_doc()
    bundle = build_study_bundle_from_document(doc)
    assert bundle.summary
    # quiz puede ser vacío si el texto es muy corto, solo verificamos que no crashea
    assert isinstance(bundle.quiz_questions, list)


def test_returns_studybundle():
    from core.studycore.models import StudyBundle
    doc = _make_doc()
    bundle = build_study_bundle_from_document(doc)
    assert isinstance(bundle, StudyBundle)
