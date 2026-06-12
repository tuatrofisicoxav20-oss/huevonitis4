"""Purga masiva del banco de glifos — pipeline automático y auditable.

Uso (desde la raíz del repo):
  python tools/purga_banco.py censo                               # censo + contact sheets
  python tools/purga_banco.py purgar --auto [--dry-run] [--hard-delete]
  python tools/purga_banco.py validar                             # render headless + cobertura

Pipeline de `purgar`: backup → censo pre → filtros duros (SPECK/GHOST/BLOB/
CLIPPED/FRAGMENTED/OUTLIER_SHAPE) → score 0-100 → DUPLICATE (sobrevive el de
mejor score por cluster) → piso de calidad → top-K por carácter → guard de
supervivencia mínima → fusibles → cuarentena (mover, no rm) → censo post.

Reconocimiento (Fase 0) — desviaciones del plan, documentadas:
  • Tinta en alpha (BUG-18): todas las métricas usan _glyph_to_gray.
  • El banco guarda crop + ~6 px de padding clampeado a la celda → CLIPPED usa
    la heurística de corte recto (≥30% del lado), no el anillo de 1 px.
  • Dedup: se reutiliza _dhash 256b + _dup_thresholds del repo (umbral strict
    por carácter) en lugar de un avg_hash de 64 bits nuevo.
  • El Writer carga del manifest (no re-escanea el dir): toda baja pasa por
    bank.remove_glyph (lock + escritura atómica + índices consistentes).
  • La app viva muta el banco (reextracción concurrente): `purgar` sin
    --dry-run ABORTA si detecta main.py corriendo.
  • La metadata de baseline está vacía en el banco actual → la alineación del
    score usa la aproximación por centroide (glyph_filters.quality_score).

Umbrales: único CONFIG en core/inkcore/glyph_filters.py (compartido con el
gate de captura de template_extract). Reportes en reports/purga_AAAAMMDD/.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, ".")
import config  # noqa: E402 — sys.path primero (script standalone)

config.ensure_dirs()
config.load_settings()

import logging  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("purga_banco")

from PIL import Image, ImageDraw  # noqa: E402

from core.inkcore.bank import GlyphBank  # noqa: E402
from core.inkcore.bank_hashing import _dup_thresholds, _glyph_to_gray, _hamming  # noqa: E402
from core.inkcore.glyph_filters import (  # noqa: E402
    CONFIG,
    compute_char_stats,
    hard_filter_reason,
    measure_glyph,
    quality_score,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / f"purga_{time.strftime('%Y%m%d')}"
VALIDATION_TEXT = (
    "El veloz murciélago hindú comía feliz cardillo y kiwi. "
    "La cigüeña tocaba el saxofón detrás del palenque de paja. "
    '¿Whisky? ¡Jamás! 0123456789 #&%@()="";:'
)


# ── Utilidades ───────────────────────────────────────────────────────────────

def app_is_running() -> bool:
    """True si la app (main.py de este repo) está corriendo: mutaría el banco."""
    try:
        out = subprocess.run(["pgrep", "-af", "main.py"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return False
    return any(str(REPO_ROOT) in line for line in out.splitlines())


def make_backup(bank_dir: Path) -> Path | None:
    """Backup tar.gz verificado del banco completo. None si falla la verificación."""
    backups_dir = bank_dir.parent.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = backups_dir / f"banco_pre_purga_{ts}.tar.gz"
    with tarfile.open(backup, "w:gz") as tf:
        tf.add(bank_dir, arcname=bank_dir.name)
    live_files = [p for p in bank_dir.rglob("*") if p.is_file()]
    with tarfile.open(backup, "r:gz") as tf:
        tar_files = [m for m in tf.getmembers() if m.isfile()]
    if len(tar_files) != len(live_files):
        print(f"FUSIBLE: backup no verificado ({len(tar_files)} en tar vs "
              f"{len(live_files)} vivos) — ABORTANDO", flush=True)
        return None
    print(f"backup OK: {backup} ({backup.stat().st_size // 1024} KB, "
          f"{len(tar_files)} archivos)", flush=True)
    return backup


def load_records(bank: GlyphBank) -> list[dict]:
    """Abre y mide cada glifo del banco. status inicial: keep / kill(MISSING_FILE)."""
    records = []
    for e in bank.get_all():
        rec = {"entry": e, "m": None, "score": None, "parts": {},
               "status": "keep", "reason": "", "detail": ""}
        p = Path(e.image_path)
        if not p.exists():
            rec.update(status="kill", reason="MISSING_FILE",
                       detail="PNG ausente del disco")
            records.append(rec)
            continue
        try:
            with Image.open(p) as im:
                rec["m"] = measure_glyph(im.convert("RGBA"))
        except Exception as exc:
            rec.update(status="kill", reason="MISSING_FILE",
                       detail=f"PNG ilegible: {exc}")
        records.append(rec)
    return records


# ── Censo y contact sheets ──────────────────────────────────────────────────

def _dist(vals: list[float]) -> dict:
    if not vals:
        return {}
    s = sorted(vals)
    return {"min": round(s[0], 4), "med": round(median(s), 4),
            "max": round(s[-1], 4)}


def census(records: list[dict], outdir: Path, tag: str) -> dict:
    """censo_{tag}.json/csv por carácter: variantes, dims, densidad, componentes."""
    outdir.mkdir(parents=True, exist_ok=True)
    by_char = defaultdict(list)
    for r in records:
        if r["m"] is not None:
            by_char[r["entry"].char].append(r["m"])
    data = {}
    for ch in sorted(by_char):
        ms = by_char[ch]
        data[ch] = {
            "variantes": len(ms),
            "ancho": _dist([m.bbox_w for m in ms]),
            "alto": _dist([m.bbox_h for m in ms]),
            "densidad": _dist([m.density for m in ms]),
            "componentes": dict(Counter(m.n_components for m in ms)),
        }
    (outdir / f"censo_{tag}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(outdir / f"censo_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["char", "variantes", "w_med", "h_med", "dens_med", "comps"])
        for ch, d in data.items():
            w.writerow([ch, d["variantes"], d["ancho"].get("med"),
                        d["alto"].get("med"), d["densidad"].get("med"),
                        json.dumps(d["componentes"])])
    deficit = sorted(ch for ch, d in data.items() if d["variantes"] < 10)
    print(f"censo_{tag}: {sum(d['variantes'] for d in data.values())} glifos, "
          f"{len(data)} chars; con <10 variantes: {deficit}", flush=True)
    return data


def contact_sheets(records: list[dict], outdir: Path, label_fn=None):
    """Grid PIL ~10 columnas por carácter; cada celda etiquetada con su índice."""
    outdir.mkdir(parents=True, exist_ok=True)
    by_char = defaultdict(list)
    for r in records:
        by_char[r["entry"].char].append(r)
    cols, cell_w, cell_h, label_h = 10, 72, 72, 14
    for ch, recs in by_char.items():
        rows = (len(recs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(recs):
            x = (i % cols) * cell_w
            y = (i // cols) * (cell_h + label_h)
            p = Path(r["entry"].image_path)
            try:
                with Image.open(p) as im:
                    g = _glyph_to_gray(im.convert("RGBA"))
                g.thumbnail((cell_w - 8, cell_h - 8))
                sheet.paste(g, (x + (cell_w - g.width) // 2,
                                y + (cell_h - g.height) // 2))
            except Exception:
                draw.text((x + 4, y + 4), "✗", fill="red")
            label = label_fn(r) if label_fn else str(r["entry"].index)
            draw.text((x + 3, y + cell_h + 1), label[:14], fill="black")
        safe = ch if ch.isalnum() else f"punct_{ord(ch)}"
        sheet.save(outdir / f"{safe}.png")


# ── Plan de purga (filtros + score + dup + piso + rank + guard) ─────────────

def build_plan(records: list[dict]) -> dict:
    """Marca cada record keep/kill con reason code. No toca disco.

    Itera hasta PUNTO FIJO: la basura contamina las medianas que calibran los
    filtros, así que tras cada pasada se recalculan las stats solo con los
    sobrevivientes y se vuelve a filtrar. Sin esto la purga no es idempotente
    (al quitar miniaturas la mediana sube y la segunda corrida mataría más).
    La cascada queda acotada por los fusibles, evaluados sobre el plan total.
    """
    cfg = CONFIG
    by_char = defaultdict(list)
    for r in records:
        by_char[r["entry"].char].append(r)

    stats = {}
    for _pass in range(20):
        new_kills = 0
        for ch, recs in by_char.items():
            ms = [r["m"] for r in recs
                  if r["status"] == "keep" and r["m"] is not None]
            stats[ch] = compute_char_stats(ch, ms, cfg)

        # Fase 3 — filtros duros (calibrados con los vivos de esta pasada)
        for r in records:
            if r["status"] == "kill" or r["m"] is None:
                continue
            verdict = hard_filter_reason(r["m"], stats[r["entry"].char], cfg)
            if verdict:
                r.update(status="kill", reason=verdict[0], detail=verdict[1])
                new_kills += 1

        # Fase 4 — score (también depende de las medianas: se recalcula)
        for r in records:
            if r["m"] is not None:
                r["score"], r["parts"] = quality_score(
                    r["m"], stats[r["entry"].char], cfg)
            else:
                r["score"] = 0.0

        # DUPLICATE — clusters por hamming ≤ umbral strict; vive el mejor score
        for ch, recs in by_char.items():
            alive = [r for r in recs if r["status"] == "keep"]
            thr = _dup_thresholds(ch)[0]
            parent = list(range(len(alive)))

            def find(i, parent=parent):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            for i in range(len(alive)):
                for j in range(i + 1, len(alive)):
                    if _hamming(alive[i]["m"].dhash, alive[j]["m"].dhash) <= thr:
                        parent[find(i)] = find(j)
            clusters = defaultdict(list)
            for i, r in enumerate(alive):
                clusters[find(i)].append(r)
            for group in clusters.values():
                if len(group) < 2:
                    continue
                group.sort(key=lambda r: r["score"], reverse=True)
                for r in group[1:]:
                    r.update(status="kill", reason="DUPLICATE",
                             detail=f"hamming ≤ {thr} del mejor "
                                    f"(score {group[0]['score']})")
                    new_kills += 1

        # Piso de calidad + cap top-K por carácter
        for ch, recs in by_char.items():
            alive = sorted((r for r in recs if r["status"] == "keep"),
                           key=lambda r: r["score"], reverse=True)
            for rank, r in enumerate(alive):
                if rank >= cfg["TOP_K"]:
                    r.update(status="kill", reason="LOW_RANK",
                             detail=f"rank {rank + 1} > top-{cfg['TOP_K']}")
                    new_kills += 1
                elif r["score"] < cfg["QUALITY_FLOOR"]:
                    r.update(status="kill", reason="LOW_SCORE",
                             detail=f"score {r['score']} < piso "
                                    f"{cfg['QUALITY_FLOOR']}")
                    new_kills += 1

        if new_kills == 0:
            break

    # Guard de supervivencia mínima: nunca dejar un char con < MIN_SURVIVORS
    recapture = []
    soft = {"LOW_SCORE", "LOW_RANK", "DUPLICATE"}
    for ch, recs in by_char.items():
        alive = [r for r in recs if r["status"] == "keep"]
        if len(alive) >= cfg["MIN_SURVIVORS"]:
            continue
        recapture.append(ch)
        killed = sorted((r for r in recs if r["status"] == "kill"),
                        key=lambda r: (r["reason"] in soft, r["score"] or 0),
                        reverse=True)
        for r in killed:
            if len(alive) >= cfg["MIN_SURVIVORS"]:
                break
            r.update(status="keep", reason="KEPT_BY_GUARD",
                     detail=f"guard: '{ch}' quedaría con <{cfg['MIN_SURVIVORS']}")
            alive.append(r)

    kills = [r for r in records if r["status"] == "kill"]
    return {"records": records, "stats": stats, "kills": kills,
            "recapture": sorted(recapture), "by_char": by_char}


def check_fuses(plan: dict, total: int) -> list[str]:
    cfg = CONFIG
    tripped = []
    kill_rate = len(plan["kills"]) / max(1, total)
    if kill_rate > cfg["FUSE_GLOBAL_KILL_RATE"]:
        tripped.append(f"tasa de kill global {kill_rate:.0%} > "
                       f"{cfg['FUSE_GLOBAL_KILL_RATE']:.0%} (umbral mal calibrado)")
    n_chars = max(1, len(plan["by_char"]))
    recap_rate = len(plan["recapture"]) / n_chars
    if recap_rate > cfg["FUSE_RECAPTURE_CHAR_RATE"]:
        tripped.append(f"{recap_rate:.0%} de los chars caen a recaptura > "
                       f"{cfg['FUSE_RECAPTURE_CHAR_RATE']:.0%}")
    return tripped


# ── Reportes ────────────────────────────────────────────────────────────────

def write_reports(plan: dict, outdir: Path, dry_run: bool, backup: Path | None,
                  pre_data: dict, post_data: dict | None):
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "eliminados.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["archivo", "char", "reason", "detalle", "score"])
        for r in plan["kills"]:
            w.writerow([Path(r["entry"].image_path).name, r["entry"].char,
                        r["reason"], r["detail"], r["score"]])
    (outdir / "recaptura.txt").write_text(
        "\n".join(plan["recapture"]) + ("\n" if plan["recapture"] else ""),
        encoding="utf-8")

    scores = sorted(r["score"] for r in plan["records"] if r["score"] is not None)
    hist = Counter(int(s // 10) * 10 for s in scores)
    hist_txt = "\n".join(f"  {b:3d}-{b + 9:3d}: {'█' * hist[b]} {hist[b]}"
                         for b in sorted(hist))
    reasons = Counter(r["reason"] for r in plan["kills"])
    by_char_counts = {
        ch: {"antes": len(recs),
             "después": sum(1 for r in recs if r["status"] == "keep")}
        for ch, recs in sorted(plan["by_char"].items())
    }
    lines = [
        "# PURGA_NOTAS",
        "",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Modo: {'DRY-RUN (sin borrados)' if dry_run else 'aplicado'}",
        f"- Backup: {backup or '(no requerido en dry-run)'}",
        f"- Glifos: {len(plan['records'])} → "
        f"{sum(1 for r in plan['records'] if r['status'] == 'keep')} "
        f"({len(plan['kills'])} kills)",
        f"- Kills por reason: {dict(reasons)}",
        f"- Recaptura: {plan['recapture'] or 'ninguno'}",
        "",
        "## Histograma de scores (piso = "
        f"{CONFIG['QUALITY_FLOOR']}; sin valle bimodal claro se mantiene el default)",
        hist_txt or "  (vacío)",
        "",
        "## Conteo por carácter (antes → después)",
        *(f"- `{ch}`: {c['antes']} → {c['después']}"
          for ch, c in by_char_counts.items()),
        "",
        "## Umbrales (CONFIG de core/inkcore/glyph_filters.py)",
        "```json",
        json.dumps({k: v for k, v in CONFIG.items()}, indent=1, ensure_ascii=False),
        "```",
        "",
        "## Desviaciones del plan (Fase 0)",
        "- Tinta en alpha (BUG-18) → métricas vía _glyph_to_gray.",
        "- CLIPPED por corte recto ≥30% del lado (el anillo de 1px mataría "
        "descendentes legítimos clampeados a la celda).",
        "- Dedup con _dhash 256b + umbral strict por carácter del repo "
        "(no se inventó un avg_hash de 64 bits).",
        "- Alineación por centroide: la metadata de baseline está vacía "
        "en el banco actual.",
        "- El banco solo contiene minúsculas+ñ: la validación exige cero "
        "pérdida de cobertura vs el set PRE-purga (mayúsculas/dígitos nunca "
        "estuvieron).",
    ]
    (outdir / "PURGA_NOTAS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"reportes en {outdir}", flush=True)


# ── Subcomandos ─────────────────────────────────────────────────────────────

def cmd_censo(bank: GlyphBank) -> int:
    records = load_records(bank)
    census(records, REPORT_DIR, "pre")
    contact_sheets(records, REPORT_DIR / "sheets_pre")
    return 0


def cmd_purgar(bank: GlyphBank, dry_run: bool, hard_delete: bool) -> int:
    if not dry_run and app_is_running():
        print("FUSIBLE: la app (main.py) está corriendo y reextrae el banco en "
              "vivo. Ciérrala y reintenta. ABORTANDO sin tocar nada.", flush=True)
        return 2

    backup = None
    if not dry_run:
        backup = make_backup(bank.bank_dir)
        if backup is None:
            return 2

    records = load_records(bank)
    total = len(records)
    pre_data = census(records, REPORT_DIR, "pre")
    contact_sheets(records, REPORT_DIR / "sheets_pre")

    plan = build_plan(records)
    tripped = check_fuses(plan, total)
    if tripped:
        for t in tripped:
            print(f"FUSIBLE: {t}", flush=True)
        write_reports(plan, REPORT_DIR, dry_run=True, backup=backup,
                      pre_data=pre_data, post_data=None)
        print("ABORTANDO sin ejecutar borrados (plan reportado).", flush=True)
        return 2

    keep = total - len(plan["kills"])
    print(f"plan: {total} glifos → {keep} sobreviven, {len(plan['kills'])} kills "
          f"({dict(Counter(r['reason'] for r in plan['kills']))})", flush=True)

    if dry_run:
        write_reports(plan, REPORT_DIR, dry_run=True, backup=backup,
                      pre_data=pre_data, post_data=None)
        return 0

    # Ejecución: cuarentena (mover, no rm) + baja vía API del banco con lock
    quarantine = REPORT_DIR / "cuarentena"
    bank.begin_batch()
    try:
        for r in plan["kills"]:
            p = Path(r["entry"].image_path)
            if not hard_delete and p.exists():
                ch = r["entry"].char
                qdir = quarantine / (ch if ch.isalnum() else f"punct_{ord(ch)}")
                qdir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, qdir / p.name)
            bank.remove_glyph(r["entry"])
    finally:
        bank.end_batch()
    bank.load()  # rebuild de índices desde disco

    # Verificación índice ↔ archivos
    entries = bank.get_all()
    missing = [e.image_path for e in entries if not Path(e.image_path).exists()]
    on_disk = {p.name for p in bank.bank_dir.glob("*.png")}
    in_manifest = {Path(e.image_path).name for e in entries}
    orphans = sorted(on_disk - in_manifest)
    if missing:
        print(f"⚠ manifest desincronizado: {len(missing)} rutas sin PNG", flush=True)
    if orphans:
        print(f"⚠ PNGs huérfanos fuera del manifest: {orphans[:10]}", flush=True)
    print(f"banco final: {len(entries)} glifos "
          f"(cuarentena en {quarantine if not hard_delete else '— hard delete'})",
          flush=True)

    post_records = load_records(bank)
    post_data = census(post_records, REPORT_DIR, "post")
    contact_sheets(post_records, REPORT_DIR / "sheets_post")
    contact_sheets(plan["kills"], REPORT_DIR / "sheets_killed",
                   label_fn=lambda r: r["reason"])
    write_reports(plan, REPORT_DIR, dry_run=False, backup=backup,
                  pre_data=pre_data, post_data=post_data)
    return 0


def cmd_validar(bank: GlyphBank) -> int:
    """Render headless del texto de validación por el pipeline del Writer."""
    from core.export.pdf_exporter import export_pages_streaming
    from core.inkcore.renderer import HandwritingRenderer
    from core.inkcore.renderer_options import RenderOptions

    entries = bank.get_all()
    bank_chars = sorted({e.char for e in entries})
    empty = [ch for ch in bank_chars if not bank.get_all(char_filter=ch)]
    print(f"banco: {len(entries)} glifos, charset: {''.join(bank_chars)}", flush=True)
    if empty:
        print(f"✗ caracteres en cero: {empty}", flush=True)
        return 2

    # El banco actual solo tiene minúsculas: se renderiza en lower y se reporta
    # qué chars del texto canónico jamás estuvieron en el banco (no es fallo de
    # la purga; la purga garantiza no PERDER cobertura, no inventarla).
    text = VALIDATION_TEXT.lower()
    never_in_bank = sorted({c for c in text if c.strip() and c not in set(bank_chars)})
    renderer = HandwritingRenderer(bank)
    options = RenderOptions()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_pdf = REPORT_DIR / "validacion_writer.pdf"
    try:
        pages = renderer.iter_pages(text, options)
        ok = export_pages_streaming(pages, str(out_pdf))
    except Exception as exc:
        print(f"✗ excepción al renderizar: {exc}", flush=True)
        return 2
    if not ok or not out_pdf.exists():
        print("✗ el export del PDF falló", flush=True)
        return 2
    print(f"✓ PDF generado: {out_pdf} ({out_pdf.stat().st_size // 1024} KB)",
          flush=True)
    if never_in_bank:
        print(f"  (chars del texto canónico que nunca estuvieron en el banco: "
              f"{''.join(never_in_bank)})", flush=True)
    pre_json = REPORT_DIR / "censo_pre.json"
    if pre_json.exists():
        pre_chars = set(json.loads(pre_json.read_text(encoding="utf-8")))
        lost = sorted(pre_chars - set(bank_chars))
        if lost:
            print(f"✗ caracteres PERDIDOS respecto al censo pre: {lost}", flush=True)
            return 2
        print("✓ cobertura intacta vs censo pre (cero caracteres perdidos)",
              flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["censo", "purgar", "validar"])
    ap.add_argument("--auto", action="store_true",
                    help="modo full automático (default; existe por contrato)")
    ap.add_argument("--dry-run", action="store_true",
                    help="planificar y reportar sin borrar nada")
    ap.add_argument("--hard-delete", action="store_true",
                    help="borrar definitivo en vez de mover a cuarentena")
    ap.add_argument("--profile", default=None, help="perfil del banco (default: activo)")
    args = ap.parse_args()

    bank = GlyphBank(args.profile)
    bank.load()
    print(f"banco: {bank.bank_dir}", flush=True)
    if args.cmd == "censo":
        return cmd_censo(bank)
    if args.cmd == "purgar":
        return cmd_purgar(bank, dry_run=args.dry_run, hard_delete=args.hard_delete)
    return cmd_validar(bank)


if __name__ == "__main__":
    raise SystemExit(main())
