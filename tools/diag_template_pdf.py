"""Diagnóstico del pipeline de plantilla contra un PDF real (harness E0).

Uso:
    python tools/diag_template_pdf.py PDF_O_DIR [--out reports/x.csv]
        [--save-debug DIR] [--dpi 300] [--pages 1,7,24] [--force-standard]

Rasteriza el PDF (o toma los PNG de una carpeta), corre el extractor de
plantilla página por página y reporta CSV + stdout: fiduciales detectados,
rotación, preset/layout, glifos extraídos, rechazos y su motivo dominante.

--save-debug guarda por página una imagen anotada: fiduciales (verde),
bbox de contenido + grilla proyectada (azul), casillas extraídas (verde) /
vacías (gris). Oro para depurar letras perdidas.

--force-standard fuerza el layout estándar (minúsculas×1) en TODAS las
páginas, reproduciendo el bug histórico de un solo layout congelado — sirve
para verificar que el gate anti-corrupción frena las páginas no estándar.
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")

import config  # noqa: E402 — sys.path primero (script standalone)

config.ensure_dirs()
config.load_settings()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.inkcore import template_extract as te  # noqa: E402
from core.inkcore.template_sheet import TemplateLayout  # noqa: E402

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("diag_template_pdf")

CSV_FIELDS = [
    "pagina", "ancho", "alto", "fiduciales", "rot", "preset",
    "n_glifos", "chars_extraidos", "n_rechazadas", "motivo_top",
    "page_agreement", "suspect", "reason", "tiempo_s",
]


class _LogTap(logging.Handler):
    """Captura los INFO/WARNING de template_extract durante una página."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(record.getMessage())


def _fiducials_by_rotation(gray: np.ndarray, lay: TemplateLayout) -> tuple[int, int]:
    """(n_rotaciones_con_4_fiduciales, ángulo de la primera que detecta o -1)."""
    hits, first = 0, -1
    for angle in (0, 90, 180, 270):
        if te._detect_fiducials(te._rotate_cw(gray, angle), lay) is not None:
            hits += 1
            if first < 0:
                first = angle
    return hits, first


def _rejection_stats(log_lines: list[str]) -> tuple[int, str]:
    """Cuenta los descartes por casilla del log y devuelve (n, motivo_top)."""
    motives: Counter[str] = Counter()
    for line in log_lines:
        m = re.search(r"descartad[ao].*\((.+?)[,)]", line)
        if m:
            motives[m.group(1).strip()] += 1
        elif "rechazad" in line:
            motives["rechazada"] += 1
    n = sum(motives.values())
    return n, (motives.most_common(1)[0][0] if motives else "")


def _annotate_page(
    gray: np.ndarray, lay: TemplateLayout, rot: int,
    chars: list[str], out_path: Path,
) -> None:
    """Imagen de debug: fiduciales, bbox de contenido, grilla y casillas."""
    g = te._rotate_cw(gray, rot)
    vis = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    fid = te._detect_fiducials(g, lay)
    if fid is not None:
        for (cx, cy), tag in zip(fid, ("TL", "TR", "BL", "BR")):
            cv2.circle(vis, (int(cx), int(cy)), 30, (0, 200, 0), 6)
            cv2.putText(vis, tag, (int(cx) + 35, int(cy)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 200, 0), 3)
    deskewed = te._deskew(g, te._estimate_skew(g))
    bb = te._grid_content_bbox(deskewed)
    if bb is not None:
        gx0, gy0, gx1, gy1 = bb
        cv2.rectangle(vis, (gx0, gy0), (gx1, gy1), (200, 120, 0), 4)
        xs = np.linspace(gx0, gx1, lay.cols + 1)
        ys = np.linspace(gy0, gy1, lay.rows + 1)
        for x in xs:
            cv2.line(vis, (int(x), gy0), (int(x), gy1), (200, 120, 0), 2)
        for y in ys:
            cv2.line(vis, (gx0, int(y)), (gx1, int(y)), (200, 120, 0), 2)
        # Marca por casilla: verde si su char salió extraído, gris si no.
        extracted = Counter(chars)
        for i in range(lay.n_cells):
            ch = lay.cell_letter(i)
            if ch is None:
                continue
            r, c = divmod(i, lay.cols)
            x0, y0 = int(xs[c]), int(ys[r])
            ok = extracted.get(ch, 0) > 0
            if ok:
                extracted[ch] -= 1
            color = (0, 180, 0) if ok else (130, 130, 130)
            cv2.putText(vis, ch, (x0 + 8, y0 + 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    cv2.imwrite(str(out_path), vis)


def _collect_pages(src: Path, dpi: int) -> tuple[list[tuple[str, int]], list[str]]:
    """Lista (ruta_png, nº de página) desde un PDF o una carpeta de imágenes."""
    tmp_dirs: list[str] = []
    if src.is_dir():
        imgs = sorted(p for p in src.iterdir()
                      if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        return [(str(p), i + 1) for i, p in enumerate(imgs)], tmp_dirs
    from core.inkcore.bulk_capture import _rasterize_pdf
    pages = _rasterize_pdf(str(src), dpi=dpi, tracker=tmp_dirs)
    return pages, tmp_dirs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="PDF o carpeta de PNGs")
    ap.add_argument("--out", default="", help="ruta del CSV de salida")
    ap.add_argument("--save-debug", default="", metavar="DIR")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--pages", default="", help="subset, p. ej. 1,7,24")
    ap.add_argument("--force-standard", action="store_true",
                    help="forzar layout minúsculas×1 en todas las páginas")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"No existe: {src}", file=sys.stderr)
        return 2
    debug_dir = Path(args.save_debug) if args.save_debug else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    pages, tmp_dirs = _collect_pages(src, args.dpi)
    if not pages:
        print("No se pudo rasterizar/encontrar páginas", file=sys.stderr)
        return 2
    subset = {int(x) for x in args.pages.split(",") if x.strip()} if args.pages else None

    lay_std = TemplateLayout()
    tap = _LogTap()
    te.logger.addHandler(tap)
    te.logger.setLevel(logging.DEBUG)

    rows: list[dict] = []
    t_total = time.time()
    extract_pdf_pages = getattr(te, "extract_pdf_pages", None)
    for page_path, pnum in pages:
        if subset and pnum not in subset:
            continue
        gray = cv2.imread(page_path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            rows.append({"pagina": pnum, "motivo_top": "imread falló"})
            continue
        h, w = gray.shape[:2]
        fid_hits, fid_angle = _fiducials_by_rotation(gray, lay_std)
        tap.records.clear()
        t0 = time.time()
        preset_name = "minusculas_x1(forzado)"
        agreement: float | None = None
        suspect = False
        reason = ""
        rot = -1
        if extract_pdf_pages is not None and not args.force_standard:
            # Camino rico (E3+): orquestador multi-layout con metadatos.
            meta = extract_pdf_pages([page_path])[0]
            results = meta["results"]
            preset_name = meta.get("preset", "?")
            rot = meta.get("rotation", -1)
            agreement = meta.get("page_agreement")
            suspect = bool(meta.get("suspect", False))
            reason = meta.get("reason", "")
        else:
            results = te.extract_from_template_auto(page_path, lay_std)
            m = re.search(r"rot (\d+)°", " ".join(tap.records))
            if m:
                rot = int(m.group(1))
        dt = time.time() - t0
        chars = [c for c, _g, _q in results]
        n_rej, top = _rejection_stats(tap.records)
        row = {
            "pagina": pnum, "ancho": w, "alto": h,
            "fiduciales": f"{4 if fid_hits else 0}@{fid_angle}" if fid_hits else "0",
            "rot": rot, "preset": preset_name,
            "n_glifos": len(results),
            "chars_extraidos": "".join(chars),
            "n_rechazadas": n_rej, "motivo_top": top,
            "page_agreement": "" if agreement is None else f"{agreement:.3f}",
            "suspect": suspect, "reason": reason,
            "tiempo_s": f"{dt:.1f}",
        }
        rows.append(row)
        print(f"pág {pnum:>2}: {w}x{h} fid={row['fiduciales']:<6} rot={rot:>3} "
              f"preset={preset_name:<22} glifos={len(results):>3} "
              f"rech={n_rej} {top}  [{dt:.1f}s]")
        if debug_dir is not None:
            _annotate_page(gray, lay_std, max(rot, 0), chars,
                           debug_dir / f"pag_{pnum:02d}.png")

    te.logger.removeHandler(tap)
    print(f"\nTotal: {time.time() - t_total:.0f}s — {len(rows)} páginas")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            wcsv = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            wcsv.writeheader()
            for r in rows:
                wcsv.writerow({k: r.get(k, "") for k in CSV_FIELDS})
        print(f"CSV → {out}")
    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
