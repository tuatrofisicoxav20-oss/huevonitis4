"""Round-trip serialization tests for all dataclasses."""
import json
from core.models import (
    ClientJob, GlyphEntry, LineElement, Page, Payment, Project,
    RectElement, TextElement,
)
from core.serializer import (
    job_from_dict, job_to_dict,
    page_from_dict, page_to_dict,
    payment_from_dict, payment_to_dict,
    project_from_dict, project_to_dict,
)


def test_project_round_trip():
    proj = Project(name="Test", description="desc")
    proj.pages = [Page(name="P1")]
    d = project_to_dict(proj)
    proj2 = project_from_dict(d)
    assert proj2.name == "Test"
    assert proj2.description == "desc"
    assert len(proj2.pages) == 1
    assert proj2.pages[0].name == "P1"
    assert proj2.id == proj.id


def test_project_status_preserved():
    proj = Project(status="Entregado")
    d = project_to_dict(proj)
    proj2 = project_from_dict(d)
    assert proj2.status == "Entregado"


def test_page_with_elements_round_trip():
    page = Page(name="Página 2")
    te = TextElement(text="Hola", font_size=16)
    re = RectElement(fill_color="#FF0000")
    le = LineElement(x2=200.0, y2=200.0)
    page.elements = [te, re, le]
    d = page_to_dict(page)
    page2 = page_from_dict(d)
    assert len(page2.elements) == 3
    assert page2.elements[0].text == "Hola"
    assert page2.elements[1].fill_color == "#FF0000"
    assert page2.elements[2].x2 == 200.0


def test_project_json_stable():
    proj = Project(name="Stable")
    serialized = json.dumps(project_to_dict(proj))
    deserialized = json.loads(serialized)
    proj2 = project_from_dict(deserialized)
    assert proj2.name == proj.name
    assert proj2.id == proj.id


def test_client_job_round_trip():
    job = ClientJob(client_name="María", pages=5, urgency="Urgente", price_mxn=250.0)
    d = job_to_dict(job)
    job2 = job_from_dict(d)
    assert job2.client_name == "María"
    assert job2.pages == 5
    assert job2.urgency == "Urgente"
    assert job2.price_mxn == 250.0
    assert job2.id == job.id


def test_payment_round_trip():
    pay = Payment(client_name="Luis", amount=100.0, is_advance=True)
    d = payment_to_dict(pay)
    pay2 = payment_from_dict(d)
    assert pay2.client_name == "Luis"
    assert pay2.amount == 100.0
    assert pay2.is_advance is True


def test_glyph_entry_defaults():
    g = GlyphEntry(char="a", quality_score=0.8, tier="Gold")
    assert g.char == "a"
    assert g.tier == "Gold"


def test_project_default_status():
    p = Project()
    assert p.status == "Borrador"
