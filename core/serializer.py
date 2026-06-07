from core.models import (
    ClientJob,
    GlyphEntry,
    ImageElement,
    LineElement,
    Page,
    Payment,
    Project,
    RectElement,
    TextElement,
)


def element_to_dict(el) -> dict:
    d = {k: v for k, v in el.__dict__.items()}
    return d


def element_from_dict(d: dict):
    t = d.get("element_type", "text")
    d = {k: v for k, v in d.items()}
    if t == "text":
        obj = TextElement()
    elif t == "image":
        obj = ImageElement()
    elif t == "rect":
        obj = RectElement()
    elif t == "line":
        obj = LineElement()
    else:
        obj = TextElement()
    for k, v in d.items():
        if hasattr(obj, k):
            setattr(obj, k, v)
    return obj


def page_to_dict(page: Page) -> dict:
    return {
        "id": page.id,
        "name": page.name,
        "width": page.width,
        "height": page.height,
        "background_color": page.background_color,
        "elements": [element_to_dict(e) for e in page.elements],
    }


def page_from_dict(d: dict) -> Page:
    page = Page()
    page.id = d.get("id", page.id)
    page.name = d.get("name", page.name)
    page.width = d.get("width", page.width)
    page.height = d.get("height", page.height)
    page.background_color = d.get("background_color", page.background_color)
    page.elements = [element_from_dict(e) for e in d.get("elements", [])]
    return page


def project_to_dict(proj: Project) -> dict:
    return {
        "id": proj.id,
        "name": proj.name,
        "created_at": proj.created_at,
        "modified_at": proj.modified_at,
        "description": proj.description,
        "status": proj.status,
        "pages": [page_to_dict(p) for p in proj.pages],
    }


def project_from_dict(d: dict) -> Project:
    proj = Project()
    proj.id = d.get("id", proj.id)
    proj.name = d.get("name", proj.name)
    proj.created_at = d.get("created_at", proj.created_at)
    proj.modified_at = d.get("modified_at", proj.modified_at)
    proj.description = d.get("description", proj.description)
    proj.status = d.get("status", proj.status)
    proj.pages = [page_from_dict(p) for p in d.get("pages", [])]
    if not proj.pages:
        proj.pages = [Page()]
    return proj


def job_to_dict(job: ClientJob) -> dict:
    return job.__dict__.copy()


def job_from_dict(d: dict) -> ClientJob:
    job = ClientJob()
    for k, v in d.items():
        if hasattr(job, k):
            setattr(job, k, v)
    return job


def payment_to_dict(p: Payment) -> dict:
    return p.__dict__.copy()


def payment_from_dict(d: dict) -> Payment:
    pay = Payment()
    for k, v in d.items():
        if hasattr(pay, k):
            setattr(pay, k, v)
    return pay


def glyph_to_dict(g: GlyphEntry) -> dict:
    return {
        "char": g.char,
        "image_path": g.image_path,
        "quality_score": g.quality_score,
        "tier": g.tier,
        "ink_coverage": g.ink_coverage,
        "index": g.index,
        "predicted_char": g.predicted_char,
        "label_confidence": g.label_confidence,
        "detector_sources": list(g.detector_sources),
    }


def glyph_from_dict(d: dict) -> GlyphEntry:
    g = GlyphEntry()
    for k in ("char", "image_path", "quality_score", "tier", "ink_coverage", "index"):
        if k in d:
            setattr(g, k, d[k])
    g.predicted_char = d.get("predicted_char")
    g.label_confidence = d.get("label_confidence")
    g.detector_sources = list(d.get("detector_sources") or [])
    return g
