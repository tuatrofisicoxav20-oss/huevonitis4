import config
from core.businesscore.models import ClientJob

URGENCY_MULTIPLIERS = {
    "Normal": 1.0,
    "Urgente": 1.5,
    "Ultra-urgente": 2.2,
}

TYPE_MULTIPLIERS = {
    "Apunte": 1.0,
    "Tarea": 1.2,
    "Guía": 1.3,
    "Resumen": 0.8,
    "Otro": 1.0,
}


def calculate_price(job: ClientJob) -> float:
    pages = max(1, int(job.pages))  # guard: pages must be >= 1 to avoid zero/negative price
    base = config.BASE_PRICE_PER_PAGE_MXN * pages
    urgency = URGENCY_MULTIPLIERS.get(job.urgency, 1.0)
    job_type = TYPE_MULTIPLIERS.get(job.job_type, 1.0)
    complexity = 1.0 + (pages * 0.015)
    return round(base * urgency * job_type * complexity, 2)


def get_price_breakdown(job: ClientJob) -> dict:
    pages = max(1, int(job.pages))  # guard: pages must be >= 1 to avoid zero/negative price
    base = config.BASE_PRICE_PER_PAGE_MXN * pages
    urgency_m = URGENCY_MULTIPLIERS.get(job.urgency, 1.0)
    type_m = TYPE_MULTIPLIERS.get(job.job_type, 1.0)
    complexity = 1.0 + (pages * 0.015)
    total = round(base * urgency_m * type_m * complexity, 2)
    return {
        "base": round(base, 2),
        "urgency_multiplier": urgency_m,
        "type_multiplier": type_m,
        "complexity_factor": round(complexity, 3),
        "total": total,
        "advance_suggested": round(total * 0.5, 2),
    }


def generate_whatsapp_message(job: ClientJob, price: float) -> str:
    return (
        f"Hola {job.client_name} 👋\n\n"
        f"Te comparto la cotización para tu {job.job_type.lower()}:\n\n"
        f"📄 Páginas: {job.pages}\n"
        f"⚡ Urgencia: {job.urgency}\n"
        f"💰 Total: ${price:,.2f} MXN\n"
        f"💳 Anticipo (50%): ${round(price * 0.5, 2):,.2f} MXN\n"
        f"📅 Entrega: {job.deadline or 'Por acordar'}\n\n"
        f"¿Te parece bien? Confirma para empezar. ✅"
    )
