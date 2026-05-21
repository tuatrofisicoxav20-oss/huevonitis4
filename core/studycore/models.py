from dataclasses import dataclass, field


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
