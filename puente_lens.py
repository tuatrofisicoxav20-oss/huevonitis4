#!/usr/bin/env python3
"""puente_lens.py — Puente Google Lens → Huevonitis (v1: feo pero funcional).

FLUJO:
    1. Escaneas a mano → PDF/foto.
    2. Lo pasas por Google Lens (cel o lens.google.com) y copias el texto.
    3. Pegas ese texto en un archivo .txt (UTF-8).
    4. Corres este script con ese .txt.
    5. Sale un PDF en tu letra, listo para imprimir.

Este puente NO hace OCR (eso es Lens, afuera) ni reimplementa el render
(eso es HandwritingRenderer, que ya funciona). Es SOLO pegamento: limpia el
texto crudo de Lens y se lo da a tu pipeline real. Si algo del render se ve
mal, el problema está en el banco/renderer, no aquí.

USO:
    python puente_lens.py entrada.txt
    python puente_lens.py entrada.txt -o salida.pdf
    python puente_lens.py entrada.txt --profile mi_perfil --no-lineas
    python puente_lens.py entrada.txt --diag      # reporte de chars faltantes
    echo "texto suelto" | python puente_lens.py -  # lee de stdin

SALIDA:
    Por defecto escribe <entrada>.pdf junto al .txt de entrada.
    Imprime al final qué caracteres de tu texto NO están en el banco
    (esos saldrían con el fallback rojo o se omitirían).
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 1. LIMPIEZA DE TEXTO — las costuras frágiles del OCR de Lens viven aquí.
# ─────────────────────────────────────────────────────────────────────────────

# Caracteres "tipográficos" que Lens devuelve y que tu banco casi seguro NO
# capturó (capturaste teclas físicas). Se normalizan al equivalente ASCII que
# tu banco sí tiene. Esto evita que media página caiga al fallback rojo.
_NORMALIZE_MAP = {
    # Comillas curvas → rectas
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u00ab": '"', "\u00bb": '"',          # « »
    # Guiones largos/medios → guion normal
    "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    # Puntos suspensivos → tres puntos
    "\u2026": "...",
    # Espacios raros (no-break, fino, etc.) → espacio normal
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u200a": " ",
    "\u2007": " ", "\u2008": " ", "\ufeff": "",   # BOM → nada
    # Viñetas que Lens mete al inicio de línea → guion
    "\u2022": "-", "\u25cf": "-", "\u25aa": "-", "\u2023": "-",
    # Multiplicación/comilla prima ocasionales
    "\u00d7": "x", "\u2032": "'", "\u2033": '"',
}


def _strip_accents_fallback(ch: str) -> str:
    """Último recurso: descompone un char acentuado a su base (á→a).

    SOLO se usa para chars que el banco no tiene. Conserva la ñ aparte
    (la tratamos como letra propia: en español NO es 'n' con tilde a efectos
    de escritura). Devuelve "" si no hay base utilizable.
    """
    if ch in ("ñ", "Ñ"):
        return ch
    decomp = unicodedata.normalize("NFD", ch)
    base = "".join(c for c in decomp if unicodedata.category(c) != "Mn")
    return base if base else ""


def clean_lens_text(raw: str) -> str:
    """Normaliza el texto crudo de Lens a algo que el banco pueda renderizar.

    Pasos, en orden:
      1. Normaliza Unicode (NFC) — unifica representaciones de acentos.
      2. Sustituye chars tipográficos por sus equivalentes ASCII (_NORMALIZE_MAP).
      3. Colapsa los saltos de línea basura de Lens:
         - 3+ saltos seguidos → doble (separación de párrafo, máx).
         - Un salto SUELTO entre dos líneas con texto = corte de renglón del
           OCR, no del autor → se une con espacio. Un salto que va seguido de
           línea vacía, viñeta, o mayúscula tras punto se RESPETA (es párrafo).
      4. Quita espacios dobles y espacios al inicio/fin de cada línea.
    """
    if not raw:
        return ""

    # 1. Unicode coherente
    text = unicodedata.normalize("NFC", raw)

    # 2. Reemplazos tipográficos directos
    text = "".join(_NORMALIZE_MAP.get(c, c) for c in text)

    # Normalizar fin de línea de Windows/Mac
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Colapso de saltos de línea.
    # Primero protegemos los saltos "de párrafo de verdad": doble salto, o
    # salto seguido de viñeta/guion de lista, o de número de lista.
    # Marcamos esos con un centinela para no tocarlos en el unwrap.
    SENT = "\x00PARA\x00"
    # 3+ saltos → 2 (un párrafo no necesita más de una línea en blanco)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # doble salto = párrafo: protegerlo
    text = text.replace("\n\n", SENT)
    # salto antes de viñeta/lista = párrafo: protegerlo
    text = re.sub(r"\n(?=\s*(?:[-*]\s|\d+[.)]\s))", SENT, text)

    # Lo que quede como "\n" suelto es un corte de renglón del OCR: unir.
    # Si la línea previa terminó con guion (palabra cortada por Lens), pegar
    # SIN espacio y sin el guion; si no, unir con un espacio.
    text = re.sub(r"-\n", "", text)        # palabra cortada: "ad-\nministra" → "administra"
    text = text.replace("\n", " ")          # resto de cortes de renglón → espacio

    # Restaurar los párrafos protegidos como doble salto real.
    text = text.replace(SENT, "\n\n")

    # 4. Limpieza de espacios.
    # Colapsar espacios/tabs múltiples a uno.
    text = re.sub(r"[ \t]+", " ", text)
    # Quitar espacio al inicio/fin de cada línea.
    text = "\n".join(line.strip() for line in text.split("\n"))
    # Quitar líneas en blanco sobrantes al principio/final del documento.
    text = text.strip()

    return text


# ─────────────────────────────────────────────────────────────────────────────
# 2. DIAGNÓSTICO — qué chars del texto NO están en el banco.
# ─────────────────────────────────────────────────────────────────────────────

def missing_chars_report(text: str, bank) -> set[str]:
    """Devuelve el set de caracteres (no-espacio) del texto que el banco no
    puede renderizar — ni con char exacto ni con su minúscula.

    Replica la lógica de selección del layout (_select_entry) para que el
    reporte coincida con lo que realmente pasaría al renderizar.
    """
    missing: set[str] = set()
    seen: set[str] = set()
    for ch in text:
        if ch.isspace() or ch in seen:
            continue
        seen.add(ch)
        entry = bank.select_glyph(ch)
        if entry is None and ch.lower() != ch:
            entry = bank.select_glyph(ch.lower())
        if entry is None:
            missing.add(ch)
    return missing


# ─────────────────────────────────────────────────────────────────────────────
# 3. PIPELINE — texto limpio → tu renderer → PDF.
# ─────────────────────────────────────────────────────────────────────────────

def render_to_pdf(
    text: str,
    out_path: Path,
    *,
    profile_id: str | None = None,
    draw_lines: bool = True,
    font_size: int = 0,
    diag: bool = False,
) -> dict:
    """Renderiza `text` con el HandwritingRenderer real y exporta un PDF.

    Devuelve un dict con métricas del run (páginas, chars faltantes, ruta).
    Importa el pipeline de Huevonitis AQUÍ dentro (no arriba) para que el
    módulo se pueda importar y testear la limpieza de texto sin arrastrar
    todo el repo.
    """
    # Imports del repo real — requieren correr DENTRO del proyecto Huevonitis.
    try:
        from core.inkcore.bank import GlyphBank
        from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    except ImportError as exc:
        raise SystemExit(
            "ERROR: no se pudo importar el pipeline de Huevonitis.\n"
            f"  Detalle: {exc}\n"
            "  → Corré este script DESDE la raíz del repo, p.ej.:\n"
            "      python -m puente_lens entrada.txt\n"
            "    o con el venv del proyecto activado y el PYTHONPATH correcto."
        ) from exc

    bank = GlyphBank(profile_id)          # autocarga el manifest del perfil
    n_glyphs = len(bank.get_all())
    if n_glyphs == 0:
        raise SystemExit(
            f"ERROR: el banco del perfil '{bank.profile_id}' está vacío.\n"
            "  → Capturá glifos antes de usar el puente."
        )

    # Reporte de faltantes ANTES de render (para avisar aunque el render falle).
    missing = missing_chars_report(text, bank)

    # OJO: el style trae su propio background_style y apply_style() lo aplica
    # ANTES que draw_lines, así que el default "Limpio" (→ hoja_blanca, sin
    # renglones) PISA un draw_lines=True suelto. Para que las rayas salgan de
    # verdad hay que pedir un estilo de libreta: "Examen" ancla el texto a los
    # renglones impresos (snap a libreta) con jitter discreto. Sin rayas se
    # mantiene "Limpio" (hoja blanca).
    style = "Examen" if draw_lines else "Limpio"
    options = RenderOptions(
        style=style,
        draw_lines=draw_lines,        # True = render sobre renglones (snap a libreta)
        font_size=font_size,          # 0 = autocalcula desde el DPI
        allow_font_fallback=diag,     # en --diag marca faltantes en rojo (visible)
    )

    renderer = HandwritingRenderer(bank)
    pages = renderer.render_pages(text, options)
    if not pages:
        raise SystemExit("ERROR: el renderer no produjo páginas (texto vacío tras limpieza?).")

    # Exportar PDF con PIL (las páginas ya son imágenes RGB).
    # save_all + append_images = multipágina nativo, sin dependencias extra.
    first, rest = pages[0], pages[1:]
    if first.mode != "RGB":
        first = first.convert("RGB")
    rest = [p.convert("RGB") if p.mode != "RGB" else p for p in rest]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    first.save(
        str(out_path), "PDF", save_all=True, append_images=rest,
        resolution=float(getattr(options, "render_dpi", 150)),
    )

    return {
        "out": out_path,
        "pages": len(pages),
        "glyphs_in_bank": n_glyphs,
        "missing": missing,
        "profile": bank.profile_id,
        "chars_in": len(text),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLI.
# ─────────────────────────────────────────────────────────────────────────────

def _read_input(src: str) -> str:
    """Lee el texto de entrada: archivo .txt o '-' para stdin."""
    if src == "-":
        return sys.stdin.read()
    p = Path(src)
    if not p.exists():
        raise SystemExit(f"ERROR: no existe el archivo de entrada: {src}")
    # utf-8-sig se come un BOM si Lens/Notepad lo metió.
    return p.read_text(encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Puente Google Lens → Huevonitis: texto OCR → PDF en tu letra.",
    )
    ap.add_argument("entrada", help="archivo .txt con el texto de Lens, o '-' para stdin")
    ap.add_argument("-o", "--output", help="ruta del PDF de salida (default: <entrada>.pdf)")
    ap.add_argument("--profile", default=None, help="profile_id del banco (default: el de config)")
    ap.add_argument("--no-lineas", action="store_true",
                    help="render sobre hoja sin renglones (default: con renglones)")
    ap.add_argument("--font-size", type=int, default=0,
                    help="tamaño de fuente en px (default: 0 = automático)")
    ap.add_argument("--diag", action="store_true",
                    help="marca en ROJO los chars que faltan en el banco (preview)")
    ap.add_argument("--dump-clean", action="store_true",
                    help="además, guarda el texto ya limpio en <salida>.clean.txt para inspección")
    args = ap.parse_args(argv)

    raw = _read_input(args.entrada)
    clean = clean_lens_text(raw)

    if not clean:
        print("AVISO: el texto quedó vacío tras la limpieza. Nada que renderizar.")
        return 1

    # Resolver ruta de salida.
    if args.output:
        out_path = Path(args.output)
    elif args.entrada == "-":
        out_path = Path("salida_puente.pdf")
    else:
        out_path = Path(args.entrada).with_suffix(".pdf")

    if args.dump_clean:
        clean_path = out_path.with_suffix(".clean.txt")
        clean_path.write_text(clean, encoding="utf-8")
        print(f"  texto limpio guardado en: {clean_path}")

    info = render_to_pdf(
        clean, out_path,
        profile_id=args.profile,
        draw_lines=not args.no_lineas,
        font_size=args.font_size,
        diag=args.diag,
    )

    # Reporte final.
    print("\n── Puente Lens: listo ─────────────────────────────")
    print(f"  PDF:            {info['out']}")
    print(f"  Páginas:        {info['pages']}")
    print(f"  Perfil banco:   {info['profile']}  ({info['glyphs_in_bank']} glifos)")
    print(f"  Chars de texto: {info['chars_in']}")
    if info["missing"]:
        faltan = " ".join(sorted(repr(c) for c in info["missing"]))
        print(f"  ⚠ Chars SIN glifo en el banco ({len(info['missing'])}): {faltan}")
        print("    → esos salieron omitidos (o en rojo si usaste --diag).")
        print("    → captúralos para que aparezcan en tu letra.")
    else:
        print("  ✓ Todos los caracteres del texto tienen glifo en el banco.")
    print("───────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
