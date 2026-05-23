"""
Votación entre predicciones de múltiples labelers para un mismo glifo.
Estrategias: majority, highest_conf, consensus.
"""
from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)


def vote(
    predictions: dict[str, tuple[str, float]],
    strategy: str,
) -> tuple[str, float, bool]:
    """Combina predicciones de múltiples labelers.

    Args:
        predictions: {labeler_name: (char_predicho, confianza)}
        strategy: "majority" | "highest_conf" | "consensus"

    Returns:
        (char_final, confianza_combinada, hay_consenso)
    """
    if not predictions:
        return ("?", 0.0, False)

    if len(predictions) == 1:
        char, conf = next(iter(predictions.values()))
        return (char or "?", conf, True)

    if strategy == "majority":
        return _vote_majority(predictions)
    elif strategy == "highest_conf":
        return _vote_highest_conf(predictions)
    elif strategy == "consensus":
        return _vote_consensus(predictions)
    else:
        logger.warning("Estrategia de voto desconocida '%s', usando highest_conf", strategy)
        return _vote_highest_conf(predictions)


def _vote_majority(
    predictions: dict[str, tuple[str, float]]
) -> tuple[str, float, bool]:
    """Majority: gana el char más votado. Empates: mayor confianza promedio."""
    votes: dict[str, list[float]] = {}
    for _, (char, conf) in predictions.items():
        votes.setdefault(char or "?", []).append(conf)

    max_votes = max(len(v) for v in votes.values())
    candidates = {c: v for c, v in votes.items() if len(v) == max_votes}

    # Desempate por confianza promedio
    winner = max(candidates, key=lambda c: sum(candidates[c]) / len(candidates[c]))
    avg_conf = sum(candidates[winner]) / len(candidates[winner])
    n_total = len(predictions)
    has_consensus = max_votes >= (n_total + 1) // 2  # mayoría simple

    # Combinar confianzas de todos los que votaron al ganador
    return (winner, round(avg_conf, 4), has_consensus)


def _vote_highest_conf(
    predictions: dict[str, tuple[str, float]]
) -> tuple[str, float, bool]:
    """Highest confidence: gana el labeler con mayor confianza individual."""
    best_char = "?"
    best_conf = -1.0
    for _, (char, conf) in predictions.items():
        if conf > best_conf:
            best_conf = conf
            best_char = char or "?"

    # Hay consenso si todos coinciden en el char ganador
    all_chars = [c for c, _ in predictions.values()]
    has_consensus = len(set(all_chars)) == 1

    return (best_char, round(max(0.0, best_conf), 4), has_consensus)


def _vote_consensus(
    predictions: dict[str, tuple[str, float]]
) -> tuple[str, float, bool]:
    """Consensus: solo acepta si TODOS los labelers coinciden.
    Si hay discrepancia devuelve ("?", confianza_media, False).
    """
    chars = [c for c, _ in predictions.values()]
    confs = [f for _, f in predictions.values()]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    unique = set(chars)
    if len(unique) == 1:
        return (chars[0] or "?", round(avg_conf, 4), True)

    # Sin consenso
    return ("?", round(avg_conf * 0.5, 4), False)
