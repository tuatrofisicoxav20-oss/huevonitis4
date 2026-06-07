"""Verifica que el dedup acepta glifos genuinamente distintos.

BUG-18: antes del fix, _avg_hash sobre RGBA daba el mismo string para
TODOS los glifos (hamming=0). Este script prueba que ahora cada variante
visible recibe un hash diferente y se acepta correctamente.

Exit 0 = dedup funciona; exit 1 = algo está mal.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Aislamos el banco a un tempdir para no tocar el del usuario
_isolated = tempfile.mkdtemp(prefix="h4_dedup_test_")
os.environ["HOME"] = _isolated

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def main() -> int:
    import config
    config.DATA_DIR = Path(_isolated) / ".local/share/huevonitis4"
    config.PROJECTS_DIR = config.DATA_DIR / "projects"
    config.TIPOGRAFIA_DIR = config.DATA_DIR / "tipografia"
    config.AUTOSAVE_DIR = config.DATA_DIR / "autosave"
    config.EXPORTS_DIR = config.DATA_DIR / "exports"
    config.MODELS_DIR = config.DATA_DIR / "models"
    config.OCR_CACHE_DIR = config.DATA_DIR / "ocr_cache"
    config.DEBUG_DIR = config.DATA_DIR / "debug_extractions"
    config.PROFILES_FILE = config.TIPOGRAFIA_DIR / "_profiles.json"
    config.LOG_FILE = config.DATA_DIR / "app.log"
    config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
    config.ensure_dirs()

    from PIL import Image, ImageDraw, ImageFont

    from core.inkcore.bank import GlyphBank

    def render(text: str, x_off: int = 0, y_off: int = 0) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f = None
        for path in (
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            try:
                f = ImageFont.truetype(path, 40)
                break
            except (OSError, FileNotFoundError):
                continue
        if f is None:
            f = ImageFont.load_default()
        d.text((10 + x_off, 10 + y_off), text, fill=(0, 0, 0, 255), font=f)
        return img

    bank = GlyphBank()
    tmp = config.TIPOGRAFIA_DIR / "_temp_extract"
    tmp.mkdir(parents=True, exist_ok=True)

    # 1) 5 variantes de 'a' con offsets distintos → DEBEN aceptarse todas
    print("=" * 60)
    print("Test 1: 5 'a' con offsets distintos (deben aceptarse todas)")
    print("=" * 60)
    accepted = 0
    for i, (x, y) in enumerate([(0, 0), (5, 3), (-4, -1), (2, 6), (-3, 4)]):
        p = tmp / f"a_test_{i}.png"
        render("a", x, y).save(p)
        r = bank.add_glyph("a", str(p))
        status = "✓ OK" if r else "✕ RECHAZADO"
        print(f"  add 'a' offset({x:+d},{y:+d}): {status}")
        if r:
            accepted += 1

    n_a = sum(1 for e in bank._entries if e.char == "a")
    expected = 5
    if n_a < expected:
        print(f"\n❌ FALLA: esperaba al menos {expected} 'a' guardadas, conté {n_a}")
        print("   El dedup sigue rechazando glifos visualmente distintos")
        return 1
    print(f"\n✓ {n_a} 'a' guardadas (esperado {expected}+)")

    # 2) 2 'a' IDÉNTICAS — la segunda debe rechazarse
    print()
    print("=" * 60)
    print("Test 2: 2 'a' IDÉNTICAS (la segunda debe rechazarse)")
    print("=" * 60)
    p1 = tmp / "a_dup_1.png"
    p2 = tmp / "a_dup_2.png"
    img = render("a", 0, 0)
    img.save(p1)
    img.save(p2)
    r1 = bank.add_glyph("a", str(p1))
    r2 = bank.add_glyph("a", str(p2))
    print(f"  primer add: {'✓ OK' if r1 else '✕ RECHAZADO (esperado: aceptar o ser dup de previos)'}")
    print(f"  segundo add (idéntico): {'✕ ACEPTADO (mal!)' if r2 else '✓ RECHAZADO (correcto)'}")
    if r2 is not None:
        print("\n❌ FALLA: el dedup no detecta imágenes idénticas")
        return 1

    print("\n✅ Dedup sanity OK — BUG-18 corregido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
