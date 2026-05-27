"""Reproduce el flujo de guardado fuera de la UI.

Uso: python tools/diagnose_save.py

Crea un glifo sintético, lo guarda al banco real del usuario, lee el
manifest, y reporta cada paso. Útil para distinguir bug de UI vs bug
de core.

Exit code 0 = el core funciona; el bug (si lo hay) está en la UI o el wiring.
Exit code 1 = el core no guarda; hay un problema en pipeline/bank.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("diagnose_save")

# Asegurarse de que el script funciona también si se invoca desde otro cwd
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        log.error("Pillow no instalado — pip install Pillow")
        return 2

    import config
    from core.inkcore.pipeline import InkCorePipeline
    from core.models import GlyphEntry

    log.info("=== diagnose_save: chequeo de flujo core de guardado ===")
    log.info("VERSION: %s", config.VERSION)
    log.info("TIPOGRAFIA_DIR: %s", config.TIPOGRAFIA_DIR)

    config.ensure_dirs()

    # 1) Generar un PNG sintético en _temp_extract con patrón distintivo
    #    para evitar que el dedup perceptual lo rechace.
    #    Importante: fondo BLANCO OPACO (no transparente). El hash perceptual
    #    de bank.py usa .convert("L") que ignora alpha, así que imágenes con
    #    fondo transparente + ink negro todas terminan hasheando idénticas.
    import os
    temp = config.TIPOGRAFIA_DIR / "_temp_extract"
    temp.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    seed = int.from_bytes(os.urandom(4), "big")
    rng = __import__("random").Random(seed)
    for x in range(64):
        for y in range(64):
            if rng.random() < 0.35:
                img.putpixel((x, y), (0, 0, 0, 255))
    fake = temp / f"DIAG_a_{seed:08x}.png"
    img.save(fake)
    log.info("PNG sintético escrito: %s (%d bytes, seed=%x)", fake, fake.stat().st_size, seed)

    # 2) Inicializar pipeline y leer estado pre-guardado
    pipe = InkCorePipeline()
    pre_count = len(pipe.bank._entries)
    log.info("Banco inicial: %d entries", pre_count)

    # Contar cuántos 'a' hay para no inflar el resultado
    pre_a = sum(1 for e in pipe.bank._entries if e.char == "a")
    log.info("Entries con char='a' antes: %d", pre_a)

    # 3) Construir GlyphEntry y guardar
    g = GlyphEntry(
        char="a",
        image_path=str(fake),
        quality_score=0.9,
        tier="Gold",
        ink_coverage=0.3,
        index=999,
    )
    log.info("Llamando pipeline.save_glyphs_to_bank([%r])...", g.char)
    result = pipe.save_glyphs_to_bank([g])
    # BUG-11: ahora devuelve dict en lugar de int
    if isinstance(result, dict):
        saved = result["saved"]
        log.info("save_glyphs_to_bank devolvió stats: %s", result)
    else:
        saved = result
        log.info("save_glyphs_to_bank devolvió: saved=%d (legacy int)", saved)

    # 4) Verificar estado post
    post_count = len(pipe.bank._entries)
    post_a = sum(1 for e in pipe.bank._entries if e.char == "a")
    log.info("Banco después: %d entries (delta=%+d)", post_count, post_count - pre_count)
    log.info("Entries con char='a' después: %d (delta=%+d)", post_a, post_a - pre_a)
    log.info("Manifest existe: %s", pipe.bank.manifest_file.exists())

    if pipe.bank.manifest_file.exists():
        log.info("Manifest size: %d bytes", pipe.bank.manifest_file.stat().st_size)

    # 5) Veredicto
    if saved == 0 and post_a == pre_a:
        log.error("FALLA: el guardado no produjo entries nuevas (saved=0 y conteo 'a' no creció)")
        log.error("Si esperabas un dedup, mirar logs WARNING anteriores")
        log.error("Si no esperabas dedup, hay bug en pipeline.save_glyphs_to_bank o bank.add_glyph")
        return 1
    if saved == 0 and post_a > pre_a:
        log.warning(
            "RARO: saved=0 pero el banco tiene un 'a' nuevo. "
            "Posible bug en el contador de save_glyphs_to_bank.",
        )
        return 1
    log.info("OK — el core funciona; si el botón UI no responde, el bug está en UI/wiring")

    # Limpieza: borrar el glifo de prueba del banco para no contaminar datos reales.
    # save_glyphs_to_bank no devuelve la entry, así que tomamos la del índice
    # más alto entre los chars 'a' (es la que acabamos de agregar).
    if saved > 0:
        try:
            a_entries = [e for e in pipe.bank._entries if e.char == "a"]
            if a_entries:
                test_entry = max(a_entries, key=lambda e: e.index)
                pipe.bank.remove_glyph(test_entry)
                log.info("Limpieza: glifo de prueba %s eliminado del banco", test_entry.image_path)
        except Exception as exc:
            log.warning("Limpieza falló (no crítico): %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
