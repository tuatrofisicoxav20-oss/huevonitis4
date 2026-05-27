import contextlib
import json
import logging
import os
import random
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import config
from core.inkcore.quality import assess_glyph
from core.models import GlyphEntry

logger = logging.getLogger(__name__)

# Protects concurrent access to the manifest file.
# The extractor runs in a background thread; autosave and UI may also
# trigger bank.save() from the main thread at the same time.
_bank_lock = threading.Lock()

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def _flatten_rgba(img: "Image.Image") -> "Image.Image":
    """BUG-18: aplanar RGBA sobre fondo blanco antes de cualquier hash.

    Los glifos del extractor son RGBA con fondo transparente y tinta RGB=(0,0,0).
    Si convertimos a grayscale directamente, Image.convert("L") ignora alpha
    y todos los píxeles dan luminancia 0 → todos los hashes son iguales →
    el dedup rechaza absolutamente todo. Aplanar sobre blanco preserva la forma.
    """
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")


def _avg_hash(img: "Image.Image", size: int = 16) -> str:
    """Hash promedio (legacy). Mantenido como fallback; usa _flatten_rgba ahora."""
    import numpy as _np
    flat = _flatten_rgba(img)
    gray = flat.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    arr = _np.asarray(gray, dtype=_np.uint8)
    avg = float(arr.mean())
    bits = (arr > avg).flatten()
    return "".join("1" if b else "0" for b in bits)


def _dhash(img: "Image.Image", size: int = 16) -> str:
    """Difference hash — más estable que avg_hash frente a cambios de brillo.

    Compara cada píxel con su vecino derecho. Más discriminativo entre glifos
    visualmente distintos del mismo carácter.
    """
    import numpy as _np
    flat = _flatten_rgba(img)
    gray = flat.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    arr = _np.asarray(gray, dtype=_np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    return "".join("1" if b else "0" for b in diff.flatten())


def _hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b, strict=False)) + abs(len(a) - len(b))


def _dup_thresholds(ch: str) -> tuple[int, int]:
    if ch in ".,;:!¡?¿|'`":
        return 3, 7
    if ch in "iltI1íì":
        return 5, 10
    if ch in "mwMW":
        return 9, 16
    return 7, 13


class GlyphBank:
    def __init__(self, profile_id: str | None = None):
        """Banco de glifos asociado a un perfil de letra (v4.2).

        Si profile_id es None, usa config.DEFAULT_PROFILE_ID para mantener
        compat con callers legacy que no conocen perfiles.

        El path resuelve a TIPOGRAFIA_DIR/{profile_id}/_manifest.json.
        """
        self.profile_id = profile_id or config.DEFAULT_PROFILE_ID
        self.bank_dir = config.TIPOGRAFIA_DIR / self.profile_id
        self.manifest_file = self.bank_dir / "_manifest.json"
        self._entries: list[GlyphEntry] = []
        # PERF-03: índices por char/tier para lookups O(1) en lugar de O(N)
        self._by_char: dict[str, list[GlyphEntry]] = {}
        self._by_tier: dict[str, list[GlyphEntry]] = {}
        # PERF-01: batched save — diferir self.save() durante batch operations
        self._batch_depth = 0
        self._batch_dirty = False
        self.load()

    # ── PERF-03: índices ─────────────────────────────────────────

    def _rebuild_indices(self) -> None:
        from collections import defaultdict
        idx_char: dict[str, list[GlyphEntry]] = defaultdict(list)
        idx_tier: dict[str, list[GlyphEntry]] = defaultdict(list)
        for e in self._entries:
            idx_char[e.char].append(e)
            idx_tier[e.tier].append(e)
        self._by_char = dict(idx_char)
        self._by_tier = dict(idx_tier)

    # ── PERF-01: batched save ────────────────────────────────────

    def begin_batch(self) -> None:
        """Difiere todos los self.save() hasta el end_batch correspondiente."""
        self._batch_depth += 1

    def end_batch(self) -> None:
        """Cierra un batch. Si era el outer, flush al disco si hubo cambios."""
        self._batch_depth = max(0, self._batch_depth - 1)
        if self._batch_depth == 0 and self._batch_dirty:
            self._batch_dirty = False
            self.save()

    def load(self):
        self.bank_dir.mkdir(parents=True, exist_ok=True)
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = [self._from_dict(d) for d in data]
                # Drop entries whose PNG has been deleted manually
                missing = [e for e in self._entries if not Path(e.image_path).exists()]
                if missing:
                    logger.warning(
                        f"GlyphBank: {len(missing)} entry/entries reference missing image(s) "
                        f"and will be removed from the manifest."
                    )
                self._entries = [e for e in self._entries if Path(e.image_path).exists()]
            except json.JSONDecodeError as e:
                logger.error(f"Corrupt glyph manifest {self.manifest_file}: {e}. Rebuilding from PNGs.")
                self._entries = []
                self._scan_existing()
            except Exception as e:
                logger.error(f"Error loading glyph bank: {e}")
                self._entries = []
        else:
            self._scan_existing()
        self._rebuild_indices()

    def _scan_existing(self):
        self._entries = []
        for png in sorted(self.bank_dir.glob("*.png")):
            stem = png.stem
            parts = stem.rsplit("_", 1)
            if len(parts) == 2:
                char = parts[0]
                if char.startswith("punct_"):
                    with contextlib.suppress(Exception):
                        char = chr(int(char[6:]))
                try:
                    idx = int(parts[1])
                except ValueError:
                    idx = 0
                metrics = assess_glyph(str(png))
                # PERF-02/07: computar hash de una vez con context-managed PIL
                ph = ""
                if PIL_OK:
                    try:
                        with Image.open(png) as raw:
                            ph = _dhash(raw.convert("RGBA"))
                    except Exception:
                        pass
                self._entries.append(GlyphEntry(
                    char=char,
                    image_path=str(png),
                    quality_score=metrics["score"],
                    tier=metrics["tier"],
                    ink_coverage=metrics["ink_coverage"],
                    index=idx,
                    profile_id=self.profile_id,
                    perceptual_hash=ph,
                ))
        self.save()

    def _atomic_write(self, path: Path, data) -> None:
        """Write JSON atomically: tmp file → os.replace(), with .bak of previous."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if path.exists():
                bak = path.with_suffix(".bak")
                try:
                    shutil.copy2(path, bak)
                except OSError as e:
                    logger.warning(f"Could not create backup {bak}: {e}")
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def save(self):
        # PERF-01: si estamos dentro de un batch, marcar dirty y diferir el write
        if self._batch_depth > 0:
            self._batch_dirty = True
            return
        with _bank_lock:
            self._atomic_write(self.manifest_file, [self._to_dict(e) for e in self._entries])

    def add_glyph(
        self,
        char: str,
        source_path: str,
        *,
        predicted_char: "str | None" = None,
        label_confidence: "float | None" = None,
        detector_sources: "list | None" = None,
        quality_override: "dict | None" = None,
    ) -> "GlyphEntry | None":
        """Add glyph to bank. Returns None if it's a perceptual duplicate.

        kwargs (todos keyword-only, opcionales):
          predicted_char    — char predicho por el labeler del pipeline.
          label_confidence  — confianza del labeler (0-1).
          detector_sources  — detectores que encontraron este glifo.
          quality_override  — dict con score/tier/ink_coverage ya calculados
                              por el pipeline (evita doble cómputo de quality).
        Callers legacy add_glyph(char, path) siguen funcionando sin cambios.
        """
        logger.info("add_glyph: start char=%r source=%s", char, source_path)
        if not Path(source_path).exists():
            logger.warning("add_glyph: source image not found: %s", source_path)
            return None

        # PERF-02/07: hash del source UNA vez con context-managed Image.open
        new_hash = ""
        if PIL_OK:
            try:
                with Image.open(source_path) as raw:
                    new_hash = _dhash(raw.convert("RGBA"))
            except Exception as e:
                logger.warning("add_glyph: hash del source falló: %s", e)

        # PERF-02: dedup contra hashes cacheados en self._by_char,
        # sin re-abrir PNGs existentes.
        if new_hash:
            with _bank_lock:
                existing = self._by_char.get(char, [])
                old_hashes = [e.perceptual_hash for e in existing if e.perceptual_hash]
                if old_hashes:
                    best = min(_hamming(new_hash, h) for h in old_hashes)
                    strict, _ = _dup_thresholds(char)
                    if best <= strict:
                        logger.warning(
                            "add_glyph: %r rechazado por dedup hamming=%d <= %d",
                            char, best, strict,
                        )
                        return None

        with _bank_lock:
            existing = self._by_char.get(char, [])
            idx = max((e.index for e in existing), default=-1) + 1
            safe = char if char.isalnum() else f"punct_{ord(char)}"
            dest = self.bank_dir / f"{safe}_{idx:03d}.png"
            try:
                shutil.copy2(source_path, dest)
            except OSError as exc:
                logger.error("add_glyph: copy falló %s → %s: %s", source_path, dest, exc)
                return None
            metrics = quality_override or assess_glyph(str(dest))
            entry = GlyphEntry(
                char=char,
                image_path=str(dest),
                quality_score=metrics["score"],
                tier=metrics["tier"],
                ink_coverage=metrics["ink_coverage"],
                index=idx,
                predicted_char=predicted_char,
                label_confidence=label_confidence,
                detector_sources=list(detector_sources or []),
                profile_id=self.profile_id,
                perceptual_hash=new_hash,
            )
            self._entries.append(entry)
            # Mantener índices consistentes (PERF-03)
            self._by_char.setdefault(char, []).append(entry)
            self._by_tier.setdefault(entry.tier, []).append(entry)
        self.save()
        logger.info(
            "add_glyph: OK char=%r dest=%s tier=%s score=%.3f profile=%s",
            char, dest, entry.tier, entry.quality_score, self.profile_id,
        )
        return entry

    def remove_glyph(self, entry: GlyphEntry):
        p = Path(entry.image_path)
        # Defense in depth: only delete files under bank_dir.
        try:
            p.resolve().relative_to(self.bank_dir.resolve())
            _safe = True
        except ValueError:
            _safe = False
        if _safe and p.exists():
            try:
                p.unlink()
            except OSError as e:
                logger.warning(f"Could not remove glyph image {p}: {e}")
        elif not _safe:
            logger.warning(f"remove_glyph: image_path '{p}' outside bank_dir — not deleting")
        with _bank_lock:
            self._entries = [e for e in self._entries if e.image_path != entry.image_path]
            # PERF-03: actualizar índices
            if entry.char in self._by_char:
                self._by_char[entry.char] = [
                    e for e in self._by_char[entry.char]
                    if e.image_path != entry.image_path
                ]
            if entry.tier in self._by_tier:
                self._by_tier[entry.tier] = [
                    e for e in self._by_tier[entry.tier]
                    if e.image_path != entry.image_path
                ]
        self.save()

    def get_best_glyph(self, char: str) -> GlyphEntry | None:
        # PERF-03: lookup O(1) en _by_char en vez de scan O(N)
        candidates = self._by_char.get(char, [])
        if not candidates:
            return None
        gold = [e for e in candidates if e.tier == "Gold"]
        if gold:
            return random.choice(gold)
        silver = [e for e in candidates if e.tier == "Silver"]
        if silver:
            return random.choice(silver)
        return random.choice(candidates)

    def get_all(self, char_filter: str = "", tier_filter: str = "") -> list[GlyphEntry]:
        # PERF-03: usar índices cuando hay filtro específico
        if char_filter and tier_filter and tier_filter != "Todos":
            return [e for e in self._by_char.get(char_filter, []) if e.tier == tier_filter]
        if char_filter:
            return list(self._by_char.get(char_filter, []))
        if tier_filter and tier_filter != "Todos":
            return list(self._by_tier.get(tier_filter, []))
        return list(self._entries)

    def coverage(self) -> dict:
        chars = set(e.char for e in self._entries)
        alpha = set("abcdefghijklmnñopqrstuvwxyz")
        covered = chars & alpha
        missing = alpha - chars
        return {
            "total_glyphs": len(self._entries),
            "unique_chars": len(chars),
            "alpha_covered": len(covered),
            "alpha_missing": sorted(missing),
            "avg_quality": round(
                sum(e.quality_score for e in self._entries) / max(1, len(self._entries)), 3
            ),
        }

    def get_review_queue(self) -> list[GlyphEntry]:
        """Devuelve glifos que necesitan revisión (Bronze o quality < 0.50)."""
        return [
            e for e in self._entries
            if e.tier == "Bronze" or e.quality_score < 0.50
        ]

    def approve_glyph(self, glyph: GlyphEntry, new_tier: str = "Silver") -> bool:
        """Sube el tier de un glifo y lo quita de la cola de revisión."""
        with _bank_lock:
            for e in self._entries:
                if e.image_path == glyph.image_path:
                    old_tier = e.tier
                    e.tier = new_tier
                    # PERF-03: mantener _by_tier consistente
                    if old_tier in self._by_tier:
                        self._by_tier[old_tier] = [
                            x for x in self._by_tier[old_tier]
                            if x.image_path != glyph.image_path
                        ]
                    self._by_tier.setdefault(new_tier, []).append(e)
                    break
            else:
                return False
        self.save()
        return True

    def reject_glyph(self, glyph: GlyphEntry) -> bool:
        """Elimina un glifo del banco y su archivo de imagen."""
        self.remove_glyph(glyph)
        return True

    def rename_glyph(self, glyph: GlyphEntry, new_char: str) -> bool:
        """Cambia el carácter asignado a un glifo."""
        if not new_char:
            return False
        with _bank_lock:
            for e in self._entries:
                if e.image_path == glyph.image_path:
                    e.char = new_char
                    break
            else:
                return False
        self.save()
        return True

    def get_bank_report(self) -> dict:
        """Devuelve estadísticas completas del banco para el informe."""
        entries = self._entries
        if not entries:
            return {
                "total_glyphs": 0,
                "by_tier": {"Gold": 0, "Silver": 0, "Bronze": 0},
                "by_char": {},
                "avg_quality": 0.0,
                "coverage_pct": 0.0,
                "alpha_covered": 0,
                "alpha_missing": list("abcdefghijklmnñopqrstuvwxyz"),
                "problematic_chars": [],
                "best_chars": [],
                "session_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "review_queue_count": 0,
            }

        by_tier = {"Gold": 0, "Silver": 0, "Bronze": 0}
        by_char: dict = {}
        for e in entries:
            tier_key = e.tier if e.tier in by_tier else "Bronze"
            by_tier[tier_key] += 1
            if e.char not in by_char:
                by_char[e.char] = {"count": 0, "quality_sum": 0.0, "tier": e.tier}
            by_char[e.char]["count"] += 1
            by_char[e.char]["quality_sum"] += e.quality_score
            if e.tier == "Gold" or (e.tier == "Silver" and by_char[e.char]["tier"] == "Bronze"):
                by_char[e.char]["tier"] = e.tier

        for ch_data in by_char.values():
            ch_data["avg_quality"] = round(ch_data["quality_sum"] / max(1, ch_data["count"]), 3)

        alpha = list("abcdefghijklmnñopqrstuvwxyz")
        alpha_set = set(alpha)
        chars_set = set(by_char.keys())
        covered = chars_set & alpha_set
        missing = sorted(alpha_set - chars_set)
        coverage_pct = round(len(covered) / max(1, len(alpha_set)) * 100, 1)

        avg_quality = round(
            sum(e.quality_score for e in entries) / max(1, len(entries)), 3
        )

        problematic = [
            {"char": ch, **data}
            for ch, data in by_char.items()
            if data["avg_quality"] < 0.50
        ]
        problematic.sort(key=lambda x: x["avg_quality"])

        best = [
            {"char": ch, **data}
            for ch, data in by_char.items()
        ]
        best.sort(key=lambda x: x["avg_quality"], reverse=True)
        best_chars = best[:5]

        return {
            "total_glyphs": len(entries),
            "by_tier": by_tier,
            "by_char": by_char,
            "avg_quality": avg_quality,
            "coverage_pct": coverage_pct,
            "alpha_covered": len(covered),
            "alpha_missing": missing,
            "problematic_chars": problematic,
            "best_chars": best_chars,
            "session_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "review_queue_count": len(self.get_review_queue()),
        }

    def _to_dict(self, e: GlyphEntry) -> dict:
        return e.__dict__.copy()

    _TIER_NORMALIZE = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze"}

    def _from_dict(self, d: dict) -> GlyphEntry:
        # BUG-29: normalizar tier legacy + loguear campos faltantes para diagnóstico
        missing = [k for k in ("char", "image_path", "quality_score", "tier") if k not in d]
        if missing:
            logger.warning(
                "Manifest entry incompleto (faltan %s) — usando defaults para %s",
                missing, d.get("image_path", "?"),
            )
        entry = GlyphEntry()
        for k, v in d.items():
            if k == "tier" and isinstance(v, str):
                v = self._TIER_NORMALIZE.get(v.lower(), v)
            if hasattr(entry, k):
                setattr(entry, k, v)
        return entry
