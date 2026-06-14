#!/usr/bin/env python3
"""corrector_ia.py — Corrección conservadora de texto OCR vía Ollama local.

Tapa el último hueco del flujo: el OCR (Lens/Drive) deja el texto con unos
pocos errores ("ma"→"más", "comio"→"comió"). Este módulo se los pasa a un
modelo local (Ollama, CPU) con un prompt ESTRICTO y conservador, y devuelve
el texto corregido — sin tocar el significado, sin agregar nada.

FILOSOFÍA (acordada con Caos Orbital):
  - Conservador: corrige SOLO ortografía/OCR obvios. NO reescribe, NO interpreta,
    NO rellena huecos. Es tarea que se entrega: cambiar el contenido es peligroso.
  - Local: el texto NUNCA sale de la máquina (privacy-first, CPU, sin GPU).
  - Revisión humana obligatoria: este módulo solo PROPONE. La decisión de
    aprobar la toma el usuario en puente_lens.py antes de generar el PDF.

Modelo por defecto: llama3.2:latest — en pruebas corrigió igual que qwen2.5:14b
pero ~60x más rápido en CPU (1.6s vs 99s). El 14b queda como opción para texto
muy destrozado (--modelo qwen2.5:14b-instruct-q4_K_M).

USO COMO MÓDULO:
    from corrector_ia import corregir_texto
    corregido = corregir_texto("el nñio comio una mansana")

USO STANDALONE (para probar sin el puente):
    python corrector_ia.py "el nñio comio una mansana"
    echo "texto con errores" | python corrector_ia.py -
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:latest"
TIMEOUT_S = 120  # generoso: en CPU el 14b puede tardar; el 3b es inmediato

# Prompt de sistema: la parte MÁS importante del módulo. Cada restricción está
# para evitar un modo de falla concreto observado en modelos pequeños.
_SYSTEM_PROMPT = (
    "Eres un corrector ortográfico estricto para texto en español extraído por "
    "OCR. Tu ÚNICA tarea es corregir errores evidentes de ortografía, acentos y "
    "errores típicos de OCR (letras confundidas, palabras pegadas o partidas).\n"
    "REGLAS ABSOLUTAS:\n"
    "1. NO cambies el significado de ninguna frase.\n"
    "2. NO agregues palabras, frases, ideas ni explicaciones que no estén.\n"
    "3. NO reescribas ni 'mejores' la redacción. Respeta el estilo original.\n"
    "4. NO quites contenido. Conserva todo el texto.\n"
    "5. Si una palabra es ambigua y no estás seguro, DÉJALA como está.\n"
    "6. Conserva los saltos de párrafo (líneas en blanco) tal cual.\n"
    "7. Responde con el texto corregido y NADA MÁS: sin saludos, sin comillas "
    "alrededor, sin comentarios, sin 'aquí está el texto corregido'.\n"
)


# ─────────────────────────────────────────────────────────────────────────────
# Limpieza de la respuesta — por si el modelo mete envoltorio igual.
# ─────────────────────────────────────────────────────────────────────────────

# Frases-envoltorio que los modelos chicos cuelan a veces pese al prompt.
# Si la respuesta EMPIEZA con alguna, se recorta esa primera línea.
_WRAPPER_PREFIXES = (
    "aquí está", "aqui esta", "aquí tienes", "aqui tienes",
    "el texto corregido", "texto corregido", "claro", "por supuesto",
    "corregido:", "resultado:",
)


def _strip_wrapper(text: str) -> str:
    """Quita envoltorio conversacional que el modelo pudo agregar.

    Conservador: solo recorta la PRIMERA línea si es claramente un preámbulo,
    y quita comillas que envuelvan todo el texto. No toca el contenido real.
    """
    t = text.strip()

    # Quitar comillas tipográficas o rectas que envuelvan TODO el texto.
    pairs = [('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u00ab", "\u00bb")]
    for a, b in pairs:
        if t.startswith(a) and t.endswith(b) and len(t) > 2:
            t = t[len(a):-len(b)].strip()
            break

    # Si la primera línea es un preámbulo y hay más líneas, tirarla.
    lines = t.split("\n")
    if len(lines) > 1:
        first_low = lines[0].strip().lower().rstrip(":")
        if any(first_low.startswith(p.rstrip(":")) for p in _WRAPPER_PREFIXES):
            # Solo si la línea es CORTA (un preámbulo, no contenido real).
            if len(lines[0]) < 60:
                t = "\n".join(lines[1:]).strip()

    return t


# ─────────────────────────────────────────────────────────────────────────────
# Llamada a Ollama
# ─────────────────────────────────────────────────────────────────────────────

def ollama_disponible(url: str = OLLAMA_URL) -> bool:
    """Chequea si Ollama está vivo, pegándole a /api/tags. No lanza excepción."""
    tags_url = url.replace("/api/generate", "/api/tags")
    try:
        req = urllib.request.Request(tags_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def corregir_texto(
    texto: str,
    *,
    modelo: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = TIMEOUT_S,
) -> str:
    """Devuelve el texto corregido por el modelo local.

    Lanza RuntimeError si Ollama no responde o el modelo falla, para que el
    caller decida (p.ej. seguir sin corrección). Nunca devuelve texto vacío:
    si el modelo regresa nada utilizable, devuelve el original sin tocar.
    """
    if not texto.strip():
        return texto

    payload = {
        "model": modelo,
        "system": _SYSTEM_PROMPT,
        "prompt": f"Corrige el siguiente texto:\n\n{texto}",
        "stream": False,
        "options": {
            # temperatura baja = corrección determinista, menos "creatividad".
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo contactar a Ollama en {url}.\n"
            f"  ¿Está corriendo? Probá: ollama serve\n"
            f"  Detalle: {exc}"
        )
    except Exception as exc:
        raise RuntimeError(f"Error llamando a Ollama: {exc}")

    raw = body.get("response", "")
    cleaned = _strip_wrapper(raw)

    # Red de seguridad: si la limpieza dejó algo vacío o absurdamente corto
    # frente al original, mejor devolver el original que basura.
    if not cleaned.strip() or len(cleaned) < len(texto) * 0.4:
        return texto

    return cleaned


def diff_resumen(original: str, corregido: str) -> list[tuple[str, str]]:
    """Lista de (palabra_original, palabra_corregida) que cambiaron.

    Comparación palabra-a-palabra simple para mostrarle al usuario QUÉ cambió
    antes de aprobar. No es un diff perfecto (no maneja inserciones/borrados de
    palabras), pero para corrección ortográfica — donde el conteo de palabras
    casi siempre se mantiene — es suficiente y muy legible.
    """
    o_words = original.split()
    c_words = corregido.split()
    cambios = []
    if len(o_words) == len(c_words):
        for ow, cw in zip(o_words, c_words):
            if ow != cw:
                cambios.append((ow, cw))
    return cambios


# ─────────────────────────────────────────────────────────────────────────────
# Standalone (para probar el corrector solo, sin el puente)
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("Uso: python corrector_ia.py \"texto con errores\"")
        print("     echo \"texto\" | python corrector_ia.py -")
        return 1

    modelo = DEFAULT_MODEL
    # flag opcional --modelo NOMBRE
    if "--modelo" in argv:
        i = argv.index("--modelo")
        modelo = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    texto = sys.stdin.read() if argv[0] == "-" else " ".join(argv)

    if not ollama_disponible():
        print("✗ Ollama no responde. Prendelo con: ollama serve")
        return 2

    print(f"  modelo: {modelo}  (corrigiendo…)")
    try:
        corregido = corregir_texto(texto, modelo=modelo)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        return 2

    print("\n── ORIGINAL ───────────────────────────")
    print(texto)
    print("── CORREGIDO ──────────────────────────")
    print(corregido)
    cambios = diff_resumen(texto, corregido)
    if cambios:
        print("── CAMBIOS ────────────────────────────")
        for o, c in cambios:
            print(f"  {o!r} → {c!r}")
    else:
        print("── (sin cambios palabra-a-palabra detectables) ──")
    print("───────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
