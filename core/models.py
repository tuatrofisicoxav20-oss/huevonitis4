import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ElementType(Enum):
    TEXT = "text"
    IMAGE = "image"
    RECT = "rect"
    LINE = "line"


@dataclass
class BaseElement:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    x: float = 100
    y: float = 100
    width: float = 200
    height: float = 50
    locked: bool = False
    visible: bool = True
    element_type: str = "text"


@dataclass
class TextElement(BaseElement):
    text: str = "Texto"
    font_size: int = 14
    font_family: str = "Arial"
    color: str = "#000000"
    bg_color: str = ""
    bold: bool = False
    italic: bool = False
    element_type: str = "text"


@dataclass
class ImageElement(BaseElement):
    image_path: str = ""
    element_type: str = "image"


@dataclass
class RectElement(BaseElement):
    fill_color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 2
    element_type: str = "rect"


@dataclass
class LineElement(BaseElement):
    x2: float = 300
    y2: float = 100
    color: str = "#000000"
    line_width: int = 2
    element_type: str = "line"


@dataclass
class Page:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Página 1"
    width: int = 794
    height: int = 1123
    elements: list = field(default_factory=list)
    background_color: str = "#FFFFFF"


@dataclass
class Project:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Nuevo Proyecto"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())
    pages: list = field(default_factory=lambda: [Page()])
    description: str = ""
    status: str = "Borrador"

    def touch(self):
        self.modified_at = datetime.now().isoformat()


class JobStatus(Enum):
    DRAFT = "Borrador"
    QUOTED = "Cotizado"
    ACCEPTED = "Aceptado"
    IN_PROGRESS = "En Progreso"
    REVIEW = "Revisión"
    DELIVERED = "Entregado"
    PAID = "Pagado"
    CANCELLED = "Cancelado"


class JobType(Enum):
    APUNTE = "Apunte"
    TAREA = "Tarea"
    GUIA = "Guía"
    RESUMEN = "Resumen"
    OTRO = "Otro"


class Urgency(Enum):
    NORMAL = "Normal"
    URGENT = "Urgente"
    ULTRA = "Ultra-urgente"


@dataclass
class ClientJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str = ""
    client_phone: str = ""
    job_type: str = "Apunte"
    pages: int = 1
    urgency: str = "Normal"
    deadline: str = ""
    notes: str = ""
    status: str = "Borrador"
    price_mxn: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def touch(self):
        self.modified_at = datetime.now().isoformat()


@dataclass
class Payment:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str = ""
    client_name: str = ""
    concept: str = ""
    amount: float = 0.0
    is_advance: bool = False
    date: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))


@dataclass
class GlyphEntry:
    char: str = ""
    image_path: str = ""
    quality_score: float = 0.0
    tier: str = "Bronze"
    ink_coverage: float = 0.0
    index: int = 0
    # Metadatos opcionales generados por el pipeline ensemble (B9)
    predicted_char: str | None = None
    label_confidence: float | None = None
    detector_sources: list = field(default_factory=list)


@dataclass
class Flashcard:
    question: str = ""
    answer: str = ""
    topic: str = ""


@dataclass
class QuizQuestion:
    question: str = ""
    expected_answer: str = ""
    keywords: list = field(default_factory=list)


@dataclass
class StudyBundle:
    source_text: str = ""
    summary: str = ""
    key_terms: list = field(default_factory=list)
    flashcards: list = field(default_factory=list)
    quiz_questions: list = field(default_factory=list)
