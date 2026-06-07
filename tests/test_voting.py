"""B12: tests de voting de labelers."""
import pytest


def test_vote_majority_clear_winner():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {
        "a": ("x", 0.9),
        "b": ("x", 0.8),
        "c": ("y", 0.95),
    }
    char, _conf, consensus = vote(preds, "majority")
    assert char == "x"
    assert consensus is True


def test_vote_majority_tie_breaks_by_conf():
    from core.inkcore.glyph_labelers.voting import vote
    # "a" y "b" 1 voto cada uno; "b" tiene mayor confianza promedio
    preds = {
        "lab1": ("a", 0.5),
        "lab2": ("b", 0.9),
    }
    char, conf, _ = vote(preds, "majority")
    # Empate — gana el de mayor confianza
    assert char == "b"
    assert conf > 0.5


def test_vote_highest_conf_picks_best():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {
        "a": ("x", 0.3),
        "b": ("z", 0.95),
        "c": ("x", 0.7),
    }
    char, conf, consensus = vote(preds, "highest_conf")
    assert char == "z"
    assert conf == pytest.approx(0.95, abs=0.01)
    assert consensus is False  # no todos coinciden


def test_vote_highest_conf_consensus():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {
        "a": ("x", 0.9),
        "b": ("x", 0.8),
    }
    char, _conf, consensus = vote(preds, "highest_conf")
    assert char == "x"
    assert consensus is True


def test_vote_consensus_all_agree():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {
        "a": ("q", 0.8),
        "b": ("q", 0.9),
    }
    char, conf, consensus = vote(preds, "consensus")
    assert char == "q"
    assert consensus is True
    assert conf > 0.0


def test_vote_consensus_disagree():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {
        "a": ("p", 0.8),
        "b": ("q", 0.8),
    }
    char, _conf, consensus = vote(preds, "consensus")
    assert char == "?"
    assert consensus is False


def test_vote_empty_predictions():
    from core.inkcore.glyph_labelers.voting import vote
    char, conf, consensus = vote({}, "highest_conf")
    assert char == "?"
    assert conf == 0.0
    assert consensus is False


def test_vote_single_labeler():
    from core.inkcore.glyph_labelers.voting import vote
    preds = {"only": ("m", 0.75)}
    char, _conf, consensus = vote(preds, "majority")
    assert char == "m"
    assert consensus is True
