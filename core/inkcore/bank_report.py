"""Construcción del informe del banco (extraído de bank.py en v4.2).

`build_bank_report` es la lógica pura detrás de GlyphBank.get_bank_report():
recibe la lista de entries y el conteo de la cola de revisión y devuelve el
mismo dict de siempre. Se mantiene aparte para que bank.py no supere ~420 líneas.
"""

from datetime import datetime


def build_bank_report(entries: list, review_queue_count: int = 0) -> dict:
    """Devuelve estadísticas completas del banco para el informe."""
    if not entries:
        return {
            "total_glyphs": 0,
            "by_tier": {"Gold": 0, "Silver": 0, "Bronze": 0},
            "by_char": {},
            "avg_quality": 0.0,
            "coverage_pct": 0.0,
            "alpha_covered": 0,
            "alpha_missing": list("abcdefghijklmnñopqrstuvwxyz"),
            "problematic_chars": [],
            "best_chars": [],
            "session_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "review_queue_count": 0,
        }

    by_tier = {"Gold": 0, "Silver": 0, "Bronze": 0}
    by_char: dict = {}
    for e in entries:
        tier_key = e.tier if e.tier in by_tier else "Bronze"
        by_tier[tier_key] += 1
        if e.char not in by_char:
            by_char[e.char] = {"count": 0, "quality_sum": 0.0, "tier": e.tier}
        by_char[e.char]["count"] += 1
        by_char[e.char]["quality_sum"] += e.quality_score
        if e.tier == "Gold" or (e.tier == "Silver" and by_char[e.char]["tier"] == "Bronze"):
            by_char[e.char]["tier"] = e.tier

    for ch_data in by_char.values():
        ch_data["avg_quality"] = round(ch_data["quality_sum"] / max(1, ch_data["count"]), 3)

    alpha = list("abcdefghijklmnñopqrstuvwxyz")
    alpha_set = set(alpha)
    chars_set = set(by_char.keys())
    covered = chars_set & alpha_set
    missing = sorted(alpha_set - chars_set)
    coverage_pct = round(len(covered) / max(1, len(alpha_set)) * 100, 1)

    avg_quality = round(
        sum(e.quality_score for e in entries) / max(1, len(entries)), 3
    )

    problematic = [
        {"char": ch, **data}
        for ch, data in by_char.items()
        if data["avg_quality"] < 0.50
    ]
    problematic.sort(key=lambda x: x["avg_quality"])

    best = [
        {"char": ch, **data}
        for ch, data in by_char.items()
    ]
    best.sort(key=lambda x: x["avg_quality"], reverse=True)
    best_chars = best[:5]

    return {
        "total_glyphs": len(entries),
        "by_tier": by_tier,
        "by_char": by_char,
        "avg_quality": avg_quality,
        "coverage_pct": coverage_pct,
        "alpha_covered": len(covered),
        "alpha_missing": missing,
        "problematic_chars": problematic,
        "best_chars": best_chars,
        "session_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "review_queue_count": review_queue_count,
    }
