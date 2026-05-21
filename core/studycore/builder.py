import re
import unicodedata
from collections import Counter

from core.studycore.models import Flashcard, QuizQuestion, StudyBundle

STOPWORDS_ES = {
    'de', 'la', 'que', 'el', 'en', 'y', 'a', 'los', 'del', 'se', 'las', 'un',
    'por', 'con', 'una', 'su', 'para', 'es', 'al', 'lo', 'como', 'más', 'pero',
    'sus', 'le', 'ya', 'o', 'este', 'sí', 'porque', 'esta', 'entre', 'cuando',
    'muy', 'sin', 'sobre', 'ser', 'tiene', 'también', 'me', 'hasta', 'hay',
    'donde', 'han', 'quien', 'están', 'estado', 'desde', 'todo', 'nos', 'durante',
    'todos', 'uno', 'les', 'ni', 'contra', 'otros', 'ese', 'eso', 'ante', 'ellos',
    'e', 'esto', 'antes', 'algunos', 'unos', 'yo', 'otro', 'otras', 'otra', 'él',
    'tanto', 'esa', 'estos', 'mucho', 'cual', 'poco', 'ella', 'estar', 'estas',
    'algo', 'nosotros', 'mi', 'si', 'fue', 'son', 'ha', 'he',
}

DEFINITION_PATTERNS = [
    r'(?P<term>[\w\s]+?)\s+(?:es|son|se define como|se refiere a|consiste en|significa)\s+(?P<def>.+)',
    r'(?P<term>[\w\s]+?)\s*[:]\s*(?P<def>.+)',
    r'(?:se llama|se denomina|se conoce como)\s+(?P<term>[\w\s]+?)\s+(?:a|al|los|las)\s+(?P<def>.+)',
]


def normalize(text: str) -> str:
    text = text.lower().strip()
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    return re.findall(r'\b[a-záéíóúüñ]{3,}\b', normalize(text))


def sentence_score(sentence: str, word_freq: Counter) -> float:
    words = tokenize(sentence)
    content_words = [w for w in words if w not in STOPWORDS_ES]
    if not content_words:
        return 0.0
    return sum(word_freq.get(w, 0) for w in content_words) / len(content_words)


def extract_summary(text: str, max_sentences: int = 5) -> str:
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 30]
    if not sentences:
        return text[:500] if len(text) > 500 else text

    words = tokenize(text)
    freq = Counter(w for w in words if w not in STOPWORDS_ES)

    scored = [(sentence_score(s, freq), i, s) for i, s in enumerate(sentences)]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = sorted(scored[:max_sentences], key=lambda x: x[1])
    return ' '.join(s for _, _, s in top)


def extract_key_terms(text: str, max_terms: int = 15) -> list[str]:
    words = tokenize(text)
    content = [w for w in words if w not in STOPWORDS_ES and len(w) >= 5]
    freq = Counter(content)
    return [term for term, _ in freq.most_common(max_terms)]


def extract_flashcards(text: str, max_cards: int = 12) -> list[Flashcard]:
    cards = []
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 20]

    for sent in sentences:
        for pat in DEFINITION_PATTERNS:
            m = re.match(pat, sent, re.IGNORECASE)
            if m:
                groups = m.groupdict()
                term = groups.get('term', '').strip()
                defn = groups.get('def', '').strip()
                if term and defn and len(term) < 60:
                    cards.append(Flashcard(
                        question=f"¿Qué es {term}?",
                        answer=defn[:200],
                        topic=term,
                    ))
                    break

    if len(cards) < 4:
        words = tokenize(text)
        freq = Counter(w for w in words if w not in STOPWORDS_ES and len(w) >= 5)
        top_words = [w for w, _ in freq.most_common(20)]
        for w in top_words:
            pattern = rf'\b{re.escape(w)}\b.{{5,120}}'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                context = match.group(0)[:150]
                cards.append(Flashcard(
                    question=f"¿Qué se dice sobre '{w}'?",
                    answer=context,
                    topic=w,
                ))
            if len(cards) >= max_cards:
                break

    return cards[:max_cards]


def extract_quiz(text: str, max_questions: int = 8) -> list[QuizQuestion]:
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 40]
    questions = []

    words = tokenize(text)
    freq = Counter(w for w in words if w not in STOPWORDS_ES and len(w) >= 5)
    top = {w for w, _ in freq.most_common(30)}

    for sent in sentences:
        words_in = set(tokenize(sent))
        overlap = words_in & top
        if len(overlap) >= 2:
            masked = sent
            for w in list(overlap)[:2]:
                masked = re.sub(rf'\b{re.escape(w)}\b', '___', masked, count=1, flags=re.IGNORECASE)
            questions.append(QuizQuestion(
                question=masked,
                expected_answer=sent,
                keywords=list(overlap)[:5],
            ))
        if len(questions) >= max_questions:
            break

    return questions


def build_study_bundle(text: str) -> StudyBundle:
    if not text or not text.strip():
        return StudyBundle(source_text=text)
    return StudyBundle(
        source_text=text,
        summary=extract_summary(text),
        key_terms=extract_key_terms(text),
        flashcards=extract_flashcards(text),
        quiz_questions=extract_quiz(text),
    )


def grade_answer(expected: str, given: str, keywords: list[str]) -> float:
    exp_words = set(normalize(expected).split())
    giv_words = set(normalize(given).split())
    kw_set = {normalize(k) for k in keywords}

    overlap = exp_words & giv_words
    kw_found = kw_set & giv_words

    if not exp_words:
        return 0.0
    word_score = len(overlap) / len(exp_words)
    kw_score = len(kw_found) / len(kw_set) if kw_set else 0.5
    return round((word_score * 0.4 + kw_score * 0.6) * 100)
