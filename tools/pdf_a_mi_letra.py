#!/usr/bin/env python3
"""Convierte un PDF a un PDF con TU letra, listo para imprimir.

Uso:
    python tools/pdf_a_mi_letra.py [ruta/al/archivo.pdf]

- Si pasás una ruta, convierte ese PDF.
- Si no pasás nada, toma el PDF MÁS RECIENTE de ~/Documentos/huevonitis_import/
  (la carpeta se crea sola; dejá ahí tu PDF).

La salida queda en ~/Documentos/huevonitis_exports/apunte_YYYYMMDD_HHMMSS.pdf
y la ruta exacta se imprime al final. Wayland-safe: no abre ningún diálogo.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMPORT_DIR = Path.home() / "Documentos" / "huevonitis_import"


def _export_dir() -> Path:
    docs = Path.home() / "Documentos"
    base = docs if docs.is_dir() else Path.home()
    out = base / "huevonitis_exports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _pick_input(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser()
        if not p.exists():
            sys.exit(f"✗ No existe el archivo: {p}")
        return p
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(IMPORT_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime)
    if not pdfs:
        sys.exit(
            f"✗ No hay PDFs en {IMPORT_DIR}\n"
            f"  Dejá tu PDF ahí, o pasá la ruta: "
            f"python tools/pdf_a_mi_letra.py /ruta/archivo.pdf"
        )
    return pdfs[-1]


def main() -> None:
    import config
    config.ensure_dirs()
    config.load_settings()

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    src = _pick_input(arg)
    print(f"→ Entrada: {src}")

    # Perfil activo (mismo criterio que main.py)
    active = "default"
    try:
        import json
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                active = json.load(f).get("active_profile_id", "default") or "default"
    except Exception:
        pass

    from core.inkcore.pipeline import InkCorePipeline
    from core.inkcore.renderer import RenderOptions
    pipe = InkCorePipeline(profile_id=active)
    renderer = pipe.renderer
    if renderer is None:
        sys.exit("✗ El banco de glifos está vacío — primero capturá tu letra en la app.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _export_dir() / f"apunte_{stamp}.pdf"

    def _progress(frac, msg):
        print(f"  [{int(frac*100):3d}%] {msg}")

    from core.export.pdf_to_handwriting import convert_pdf_to_handwriting
    try:
        res = convert_pdf_to_handwriting(
            src, renderer, RenderOptions(render_dpi=150, style="Bolígrafo"), out_path,
            progress_cb=_progress,
        )
    except Exception as exc:
        sys.exit(f"✗ Error: {exc}")

    print()
    print(f"✓ PDF con tu letra: {res['out_path']}")
    print(f"  {res['n_pages']} página(s), {res['n_chars']} caracteres del texto.")
    missing = res.get("missing") or []
    if missing:
        print(f"  ⚠ Sin glifo en tu banco (se OMITEN): {' '.join(missing)}")
    downgraded = res.get("case_downgraded") or []
    if downgraded:
        print(f"  ℹ Mayúsculas usando su minúscula: {' '.join(downgraded)}")


if __name__ == "__main__":
    main()
