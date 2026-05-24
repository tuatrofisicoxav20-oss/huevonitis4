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


def _avg_hash(img: "Image.Image", size: int = 16) -> str:
    gray = img.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    px = list(gray.getdata())
    avg = sum(px) / max(1, len(px))
    return "".join("1" if p >= avg else "0" for p in px)


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
    def __init__(self):
        self.bank_dir = config.TIPOGRAFIA_DIR
        self.manifest_file = self.bank_dir / "_manifest.json"
        self._entries: list[GlyphEntry] = []
        self.load()

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
                self._entries.append(GlyphEntry(
                    char=char,
                    image_path=str(png),
                    quality_score=metrics["score"],
                    tier=metrics["tier"],
                    ink_coverage=metrics["ink_coverage"],
                    index=idx,
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
        if not Path(source_path).exists():
            logger.warning(f"add_glyph: source image not found: {source_path}")
            return None

        if PIL_OK:
            try:
                new_img = Image.open(source_path).convert("RGBA")
                new_hash = _avg_hash(new_img)
                with _bank_lock:
                    existing_snapshot = [e for e in self._entries if e.char == char]
                    old_hashes = []
                    for e in existing_snapshot:
                        if not Path(e.image_path).exists():
                            continue
                        with contextlib.suppress(Exception):
                            old_hashes.append(_avg_hash(Image.open(e.image_path).convert("RGBA")))
                    if old_hashes:
                        best = min(_hamming(new_hash, h) for h in old_hashes)
                        strict, _ = _dup_thresholds(char)
                        if best <= strict:
                            logger.debug(f"Duplicate glyph for '{char}' (hamming={best}), skipped")
                            return None
            except Exception as e:
                logger.warning(f"Hash dedup check failed: {e}")

        with _bank_lock:
            existing = [e for e in self._entries if e.char == char]
            idx = max((e.index for e in existing), default=-1) + 1
            safe = char if char.isalnum() else f"punct_{ord(char)}"
            dest = self.bank_dir / f"{safe}_{idx:03d}.png"
            shutil.copy2(source_path, dest)
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
            )
            self._entries.append(entry)
        self.save()
        return entry

    def remove_glyph(self, entry: GlyphEntry):
        p = Path(entry.image_path)
        # Defense in depth: only delete files under bank_dir.
        # Bank images are always copied into bank_dir by add_glyph(), so any
        # external path here means corruption or tampering — skip the unlink.
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
        self.save()

    def get_best_glyph(self, char: str) -> GlyphEntry | None:
        candidates = [e for e in self._entries if e.char == char]
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
        results = self._entries
        if char_filter:
            results = [e for e in results if e.char == char_filter]
        if tier_filter and tier_filter != "Todos":
            results = [e for e in results if e.tier == tier_filter]
        return results

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
                    e.tier = new_tier
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

    def _from_dict(self, d: dict) -> GlyphEntry:
        entry = GlyphEntry()
        for k, v in d.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        return entry
