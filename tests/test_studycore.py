"""Tests for studycore: build_study_bundle, grade_answer, edge cases."""
import pytest
from core.studycore.builder import build_study_bundle, grade_answer


SAMPLE_TEXT = """
La fotosíntesis es el proceso por el cual las plantas convierten la luz solar en energía.
Las plantas utilizan dióxido de carbono y agua para producir glucosa y oxígeno.
La clorofila es el pigmento que absorbe la luz solar necesaria para este proceso.
El proceso ocurre principalmente en los cloroplastos de las células vegetales.
La fotosíntesis es fundamental para la vida en la Tierra porque produce oxígeno.
"""


def test_build_bundle_returns_studybundle():
    from core.studycore.models import StudyBundle
    bundle = build_study_bundle(SAMPLE_TEXT)
    assert isinstance(bundle, StudyBundle)
    assert bundle.source_text == SAMPLE_TEXT


def test_bundle_has_summary():
    bundle = build_study_bundle(SAMPLE_TEXT)
    assert bundle.summary
    assert len(bundle.summary) > 20


def test_bundle_has_key_terms():
    bundle = build_study_bundle(SAMPLE_TEXT)
    assert len(bundle.key_terms) > 0


def test_bundle_has_flashcards():
    bundle = build_study_bundle(SAMPLE_TEXT)
    assert isinstance(bundle.flashcards, list)


def test_bundle_has_quiz_questions():
    bundle = build_study_bundle(SAMPLE_TEXT)
    assert isinstance(bundle.quiz_questions, list)


def test_bundle_cached():
    """Same text should return the exact same object."""
    b1 = build_study_bundle(SAMPLE_TEXT)
    b2 = build_study_bundle(SAMPLE_TEXT)
    assert b1 is b2


def test_bundle_cache_invalidates_on_different_text():
    b1 = build_study_bundle(SAMPLE_TEXT)
    b2 = build_study_bundle(SAMPLE_TEXT + " Extra.")
    assert b1 is not b2


def test_empty_text_returns_empty_bundle():
    bundle = build_study_bundle("")
    assert bundle.summary == ""
    assert bundle.key_terms == []
    assert bundle.flashcards == []


def test_whitespace_only_text():
    bundle = build_study_bundle("   \n\n   ")
    assert bundle.summary == ""


def test_grade_answer_perfect():
    # With no keywords, kw_score defaults to 0.5, so max is (0.4 + 0.3)*100 = 70
    score = grade_answer("la fotosíntesis produce oxígeno", "la fotosíntesis produce oxígeno", [])
    assert score == 70

def test_grade_answer_perfect_with_keywords():
    kw = ["fotosíntesis", "produce", "oxigeno"]
    score = grade_answer("la fotosíntesis produce oxígeno", "la fotosíntesis produce oxígeno", kw)
    assert score == 100


def test_grade_answer_partial():
    score = grade_answer("la fotosíntesis produce oxígeno", "fotosíntesis", ["fotosíntesis"])
    assert 0 < score < 100


def test_grade_answer_empty():
    score = grade_answer("", "cualquier cosa", [])
    assert score == 0.0


def test_grade_answer_with_keywords():
    score = grade_answer(
        "fotosíntesis proceso plantas luz",
        "fotosíntesis plantas",
        ["fotosíntesis", "plantas"],
    )
    assert score > 0
