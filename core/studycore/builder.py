import hashlib
import logging
import re
import shelve
import time
import unicodedata
from collections import Counter

import config
from core.studycore.models import Flashcard, QuizQuestion, StudyBundle

logger = logging.getLogger(__name__)

_TTL_SECONDS = 30 * 24 * 3600  # 30 días

# Caché en memoria como fallback y capa rápida
_bundle_cache: dict[str, StudyBundle] = {}


def _cache_path() -> str:
    return str(config.DATA_DIR / "study_bundle_cache")


def _disk_get(key: str) -> "StudyBundle | None":
    try:
        with shelve.open(_cache_path()) as db:
            entry = db.get(key)
            if entry is None:
                return None
            ts, bundle = entry
            if time.time() - ts > _TTL_SECONDS:
                del db[key]
                return None
            return bundle
    except Exception as exc:
        logger.debug("study_bundle disk cache read failed: %s", exc)
        return None


def _disk_put(key: str, bundle: "StudyBundle") -> None:
    try:
        with shelve.open(_cache_path()) as db:
            # Purgar entradas viejas al guardar (mantiene el archivo pequeño)
            expired = [k for k, v in db.items()
                       if isinstance(v, tuple) and time.time() - v[0] > _TTL_SECONDS]
            for k in expired:
                del db[k]
            db[key] = (time.time(), bundle)
    except Exception as exc:
        logger.debug("study_bundle disk cache write failed: %s", exc)

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
    key = hashlib.sha256(text.encode()).hexdigest()
    if key in _bundle_cache:
        return _bundle_cache[key]
    cached = _disk_get(key)
    if cached is not None:
        _bundle_cache[key] = cached
        return cached
    bundle = StudyBundle(
        source_text=text,
        summary=extract_summary(text),
        key_terms=extract_key_terms(text),
        flashcards=extract_flashcards(text),
        quiz_questions=extract_quiz(text),
    )
    _bundle_cache[key] = bundle
    _disk_put(key, bundle)
    return bundle


def build_study_bundle_from_document(doc: "object") -> StudyBundle:
    """Versión estructurada que aprovecha la jerarquía del Document.

    - Headings H + primer párrafo siguiente → Flashcard de alta confianza.
    - key_terms: headings primero, complementa con extract_key_terms(texto).
    - Quiz: solo párrafos como fuente (no headings).
    build_study_bundle(text) clásico sigue existiendo para compat.
    """
    from core.ocr.document_model import BlockType

    full_text = doc.full_text() if callable(getattr(doc, "full_text", None)) else ""
    if not full_text.strip():
        return StudyBundle(source_text=full_text)

    key = "doc:" + hashlib.sha256(full_text.encode()).hexdigest()
    if key in _bundle_cache:
        return _bundle_cache[key]
    cached = _disk_get(key)
    if cached is not None:
        _bundle_cache[key] = cached
        return cached

    all_blocks = [b for p in doc.pages for b in p.blocks]

    # ── Flashcards estructuradas (heading + párrafo siguiente) ──────
    structured_cards: list[Flashcard] = []
    for i, block in enumerate(all_blocks):
        if block.block_type == BlockType.HEADING:
            heading_text = block.text.strip()
            if not heading_text or len(heading_text) > 120:
                continue
            # Buscar el primer párrafo o list_item siguiente
            answer_text = ""
            for j in range(i + 1, min(i + 5, len(all_blocks))):
                nb = all_blocks[j]
                if nb.block_type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM):
                    answer_text = nb.text.strip()[:200]
                    break
                if nb.block_type == BlockType.HEADING:
                    break
            if answer_text:
                structured_cards.append(Flashcard(
                    question=f"¿Qué es {heading_text}?",
                    answer=answer_text,
                    topic=heading_text,
                ))

    # Complementar con heurístico si hay pocas tarjetas
    if len(structured_cards) < 4:
        heuristic = extract_flashcards(full_text, max_cards=12 - len(structured_cards))
        structured_cards.extend(heuristic)

    # ── key_terms: headings primero ─────────────────────────────────
    heading_terms = [
        b.text.strip() for b in all_blocks
        if b.block_type == BlockType.HEADING and b.text.strip()
    ]
    generic_terms = extract_key_terms(full_text, max_terms=15)
    seen: set[str] = set()
    combined_terms: list[str] = []
    for t in heading_terms + generic_terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            combined_terms.append(t)
    key_terms = combined_terms[:15]

    # ── Quiz: solo párrafos ─────────────────────────────────────────
    para_text = "\n\n".join(
        b.text for b in all_blocks
        if b.block_type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM)
    )
    quiz = extract_quiz(para_text or full_text, max_questions=8)

    bundle = StudyBundle(
        source_text=full_text,
        summary=extract_summary(full_text),
        key_terms=key_terms,
        flashcards=structured_cards[:12],
        quiz_questions=quiz,
    )
    _bundle_cache[key] = bundle
    _disk_put(key, bundle)
    return bundle


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
