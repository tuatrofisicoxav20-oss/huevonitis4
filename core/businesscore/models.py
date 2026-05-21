from dataclasses import dataclass, field
from datetime import datetime
import uuid


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


JOB_STATUSES = [
    "Borrador", "Cotizado", "Aceptado", "En Progreso",
    "Revisión", "Entregado", "Pagado", "Cancelado"
]

STATUS_COLORS = {
    "Borrador": "#6B7280",
    "Cotizado": "#3B82F6",
    "Aceptado": "#8B5CF6",
    "En Progreso": "#F97316",
    "Revisión": "#EAB308",
    "Entregado": "#22C55E",
    "Pagado": "#15803D",
    "Cancelado": "#EF4444",
}

JOB_TYPES = ["Apunte", "Tarea", "Guía", "Resumen", "Otro"]
URGENCIES = ["Normal", "Urgente", "Ultra-urgente"]
