import contextlib
import json
import logging
import os
import random
import shutil
import tempfile
import threading
from pathlib import Path

import config

# Re-export de las funciones de hashing perceptual (movidas a bank_hashing.py
# en v4.2 para mantener bank.py por debajo de ~420 líneas). Se re-importan acá
# para no romper `from core.inkcore.bank import _dhash` (los tests dependen de
# que sigan accesibles desde core.inkcore.bank). PIL_OK también se re-exporta.
from core.inkcore.bank_hashing import (  # noqa: F401
    PIL_OK,
    _avg_hash,
    _dhash,
    _dup_thresholds,
    _glyph_to_gray,
    _hamming,
)
from core.inkcore.bank_io import backfill_missing_hashes, scan_existing
from core.inkcore.bank_report import build_bank_report
from core.inkcore.bank_serial import _TIER_NORMALIZE, entry_from_dict, entry_to_dict
from core.inkcore.quality import assess_glyph
from core.models import GlyphEntry

logger = logging.getLogger(__name__)

# Protects concurrent access to the manifest file.
# The extractor runs in a background thread; autosave and UI may also
# trigger bank.save() from the main thread at the same time.
# RLock (reentrante): add_glyph mantiene el lock para dedup+append+save de forma
# atómica, y save() vuelve a adquirirlo internamente. Con un Lock simple eso sería
# deadlock; con RLock el mismo hilo puede re-entrar. (F7)
_bank_lock = threading.RLock()

# auto_curate: un glifo Gold/Silver se considera MAL CLASIFICADO si el CNN
# (juez independiente del puño) le da a la letra esperada una probabilidad por
# debajo de este piso Y su top-1 es OTRA letra. Es una segmentación errónea
# (terminó siendo otra letra) o basura; se saca de la rotación (→ Bronze).
_CURATE_MISCLASS_FLOOR = 0.05

# Pesos de muestreo por tier para la selección de ESCRITURA (select_glyph): Gold
# pesa más que Silver, pero TODAS rotan entre sí (no se colapsa a "siempre la
# mejor"). Bronze queda fuera de la rotación (papelera de auto_curate/outliers).
_SELECT_TIER_WEIGHT = {"Gold": 3.0, "Silver": 1.0, "Bronze": 0.0}

if PIL_OK:
    from PIL import Image


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
        # PERF-02: recalcular perceptual_hash para entries pre-v4.2 que no lo tienen
        self._backfill_missing_hashes()
        self._rebuild_indices()

    @staticmethod
    def _is_degenerate_hash(h: str) -> bool:
        """Un hash es inútil si está vacío o tiene todos los bits iguales.

        Los bancos guardados con el _dhash roto (tinta en alpha → imagen toda
        blanca) tienen perceptual_hash='000…0', que es truthy pero degenerado:
        su distancia hamming contra cualquier otro hash igual es 0, así que el
        dedup los toma como duplicados de todo. Hay que recomputarlos.
        """
        if not h:
            return True
        return h.count("0") == len(h) or h.count("1") == len(h)

    def _backfill_missing_hashes(self) -> None:
        """Recalcula perceptual_hash de entries sin hash o con hash degenerado.

        Delega en bank_io.backfill_missing_hashes (repara IN PLACE) y persiste
        sólo si hubo cambios. Ver esa función para el detalle de los dos casos
        que cubre (pre-v4.2 sin hash y _dhash roto colapsado a '000…0').
        """
        rebuilt = backfill_missing_hashes(self._entries, self._is_degenerate_hash)
        if rebuilt:
            try:
                self.save()
            except Exception as exc:
                logger.warning("backfill save falló (no crítico): %s", exc)

    def _scan_existing(self):
        # Delega el scan de PNGs en bank_io; el save() se mantiene acá.
        self._entries = scan_existing(self.bank_dir, self.profile_id)
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

    @staticmethod
    def _ink_mask_for_cnn(path: str):
        """Máscara binaria de tinta (255=tinta) lista para el CNN, o None.

        Mismo criterio que el renderer al recolorear: la forma sale del alpha; si
        el alpha es plano (glifo opaco legacy), de la luminancia invertida.
        """
        if not PIL_OK:
            return None
        try:
            import numpy as np
            im = Image.open(path).convert("RGBA")
            a = np.asarray(im.getchannel("A"))
            if int(a.max()) - int(a.min()) < 12:
                a = 255 - np.asarray(im.convert("L"))
            return (a > 40).astype("uint8") * 255
        except Exception:
            return None

    def auto_curate(self, classifier=None, dry_run: bool = False) -> dict:
        """Degrada a Bronze los glifos Gold/Silver que el CNN reconoce como OTRA letra.

        Usa el clasificador EMNIST (a-z) como juez independiente del texto de
        referencia del usuario: si para un glifo etiquetado 'x' el modelo da una
        P(x) ínfima Y su top-1 es otra letra, casi seguro el corte quedó mal
        (terminó siendo otra letra) o es basura. Lo saca de la rotación
        (Gold/Silver → Bronze) SIN borrar el archivo, así es reversible y el glifo
        sigue disponible si el usuario lo quiere recuperar.

        Conservador por diseño:
          • Sólo opera sobre a-z. La ñ y los dígitos no existen en EMNIST, así que
            se dejan intactos (el CNN no puede juzgarlos).
          • Nunca vacía un carácter: siempre conserva el glifo mejor puntuado de
            cada letra aunque también parezca sospechoso.
          • Si el modelo no está disponible (sin torch/sin .pt), es un no-op.

        Devuelve stats: ``{"checked", "demoted", "by_char", "available"}``.
        """
        stats = {"checked": 0, "demoted": 0, "by_char": {}, "available": False}
        if not PIL_OK:
            return stats
        try:
            from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
        except Exception:
            return stats
        clf = classifier or EMNISTCharClassifier()
        if not getattr(clf, "available", False):
            return stats
        stats["available"] = True

        demoted: list[GlyphEntry] = []
        with _bank_lock:
            for char, entries in list(self._by_char.items()):
                if char_to_label(char) is None:
                    continue  # ñ / dígitos: el CNN no aplica
                rotation = [e for e in entries if e.tier in ("Gold", "Silver")]
                if len(rotation) < 2:
                    continue  # con uno solo no se puede demover sin vaciar
                scored = []
                for e in rotation:
                    mask = self._ink_mask_for_cnn(e.image_path)
                    if mask is None:
                        continue
                    sc = clf.score(mask, char)
                    top = clf.predict_topk(mask, 1)
                    top_char = top[0][0] if top else "?"
                    scored.append((e, sc if sc is not None else -1.0, top_char))
                if len(scored) < 2:
                    continue
                stats["checked"] += len(scored)
                # Proteger siempre el mejor (mayor P(esperada)) de cada letra.
                best = max(scored, key=lambda t: t[1])
                for e, sc, top_char in scored:
                    if e is best[0]:
                        continue
                    if 0 <= sc < _CURATE_MISCLASS_FLOOR and top_char != char:
                        demoted.append(e)
                        stats["by_char"][char] = stats["by_char"].get(char, 0) + 1
            if demoted and not dry_run:
                for e in demoted:
                    e.tier = "Bronze"
                self._rebuild_indices()
        stats["demoted"] = len(demoted)
        if demoted and not dry_run:
            self.save()
        return stats

    def add_glyph(
        self,
        char: str,
        source_path: str,
        *,
        predicted_char: "str | None" = None,
        label_confidence: "float | None" = None,
        detector_sources: "list | None" = None,
        quality_override: "dict | None" = None,
        skip_dedup: bool = False,
    ) -> "GlyphEntry | None":
        """Add glyph to bank. Returns None if it's a perceptual duplicate.

        kwargs (todos keyword-only, opcionales):
          predicted_char    — char predicho por el labeler del pipeline.
          label_confidence  — confianza del labeler (0-1).
          detector_sources  — detectores que encontraron este glifo.
          quality_override  — dict con score/tier/ink_coverage ya calculados
                              por el pipeline (evita doble cómputo de quality).
          skip_dedup        — si True, NO rechaza por duplicado perceptual: se
                              guarda siempre (salvo error de I/O). Pensado para
                              el flujo de PLANTILLA, donde las casillas con
                              repeats>1 son a propósito la MISMA letra repetida
                              para capturar variación natural de la escritura; el
                              dedup por hamming las rechazaría y anularía el punto
                              de repeats, manteniendo el banco artificialmente
                              chico. El hash igual se calcula y se guarda en la
                              entry (lo usa el medoide en get_best_glyph). En el
                              flujo de imagen suelta dejarlo en False: ahí el
                              solapamiento de cajas sí puede extraer dos veces el
                              mismo glifo y el dedup aporta.
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
        # Un hash degenerado (todo ceros/unos) no sirve para deduplicar: su
        # distancia contra cualquier otro igual es 0 y rechazaría todo. Lo tratamos
        # como "sin hash" para el dedup en vez de envenenar la comparación.
        usable_hash = bool(new_hash) and not self._is_degenerate_hash(new_hash)

        # Dedup + inserción en UN SOLO lock (atómico): si el chequeo y el append
        # están en locks separados, dos llamadas concurrentes pueden pasar ambas
        # el dedup e insertar el mismo glifo dos veces (TOCTOU). Aquí no.
        with _bank_lock:
            existing = self._by_char.get(char, [])
            if usable_hash and not skip_dedup:
                # PERF-02: comparar contra hashes cacheados, ignorando degenerados
                # (un banco con basura todo-ceros no debe rechazar muestras nuevas).
                old_hashes = [
                    e.perceptual_hash for e in existing
                    if e.perceptual_hash and not self._is_degenerate_hash(e.perceptual_hash)
                ]
                if old_hashes:
                    best = min(_hamming(new_hash, h) for h in old_hashes)
                    strict, _ = _dup_thresholds(char)
                    if best <= strict:
                        logger.warning(
                            "add_glyph: %r rechazado por dedup hamming=%d <= %d",
                            char, best, strict,
                        )
                        return None
            elif new_hash and not usable_hash:
                logger.warning(
                    "add_glyph: %r con hash degenerado — se omite dedup (glifo sólido/vacío?)",
                    char,
                )
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
            # F7 — save DENTRO del lock (RLock): el estado en memoria y el manifest
            # en disco quedan atómicos; ningún otro hilo ve un punto intermedio.
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

    def get_best_glyph(self, char: str, variation: bool = False) -> GlyphEntry | None:
        """Mejor glifo para `char`.

        Salto 2 — por defecto (variation=False) devuelve la MEDOIDE del mejor
        tier disponible: la instancia más central/representativa del grupo (la que
        minimiza la distancia perceptual al resto), determinista. Con
        variation=True elige al azar dentro del tier (lo que quiere el renderer
        para que la letra manuscrita no salga robótica). En ambos casos los
        outliers ya fueron degradados de tier al extraer, así que ni la variación
        cae en una mala segmentación si hay mejores.
        """
        # PERF-03: lookup O(1) en _by_char en vez de scan O(N).
        # F7 — snapshot bajo lock: el hilo de fondo puede estar mutando la lista.
        with _bank_lock:
            candidates = list(self._by_char.get(char, []))
        if not candidates:
            return None
        gold = [e for e in candidates if e.tier == "Gold"]
        silver = [e for e in candidates if e.tier == "Silver"]
        group = gold or silver or candidates
        if variation:
            return random.choice(group)
        # Determinista: medoide por hash perceptual.
        from core.inkcore.glyph_consensus import medoid_index
        idx = medoid_index([e.perceptual_hash for e in group])
        return group[idx]

    def select_glyph(
        self,
        char: str,
        history: "dict | None" = None,
        rng: "random.Random | None" = None,
        recent_n: int = 3,
    ) -> "GlyphEntry | None":
        """Selección para ESCRITURA: muestreo ponderado por tier + memoria corta.

        Mata la repetición robótica sin colapsar a un solo glifo:
          • Muestreo PONDERADO: Gold pesa más que Silver, pero todas rotan.
          • Memoria corta: evita repetir un glifo usado en las últimas N
            apariciones de ESE carácter (N = min(recent_n, variantes-1)), así
            nunca sale el mismo glifo dos veces seguidas si hay alternativas.
          • Reproducible: si se pasa ``rng`` (random.Random con seed), el render
            es idéntico. ``history`` es un dict que mantiene el CALLER (uno por
            render) — mantiene el estado fuera del banco para no chocar con la UI
            ni con el hilo de extracción.

        Devuelve None si no hay glifos para el carácter (el caller usa fallback).
        """
        with _bank_lock:
            candidates = list(self._by_char.get(char, []))
        if not candidates:
            return None
        rnd = rng or random
        pool = [(e, _SELECT_TIER_WEIGHT.get(e.tier, 0.0)) for e in candidates]
        pool = [(e, w) for e, w in pool if w > 0] or [(e, 1.0) for e in candidates]
        # Evitar las últimas N usadas de este char (sin vaciar el pool).
        if history is not None and len(pool) > 1:
            recent = history.get(char, [])
            n = min(recent_n, len(pool) - 1)
            avoid = set(recent[-n:]) if n > 0 else set()
            filtered = [(e, w) for e, w in pool if e.image_path not in avoid]
            if filtered:
                pool = filtered
        chosen = rnd.choices([e for e, _ in pool], weights=[w for _, w in pool], k=1)[0]
        if history is not None:
            history.setdefault(char, []).append(chosen.image_path)
        return chosen

    def get_all(self, char_filter: str = "", tier_filter: str = "") -> list[GlyphEntry]:
        # PERF-03: usar índices cuando hay filtro específico.
        # F7 — todo bajo lock y devolviendo copias: nunca exponemos la lista viva
        # ni la iteramos mientras el hilo de fondo la muta.
        with _bank_lock:
            if char_filter and tier_filter and tier_filter != "Todos":
                return [e for e in self._by_char.get(char_filter, []) if e.tier == tier_filter]
            if char_filter:
                return list(self._by_char.get(char_filter, []))
            if tier_filter and tier_filter != "Todos":
                return list(self._by_tier.get(tier_filter, []))
            return list(self._entries)

    def coverage(self) -> dict:
        # F7 — snapshot bajo lock antes de agregar.
        with _bank_lock:
            _entries_snap = list(self._entries)
        chars = set(e.char for e in _entries_snap)
        alpha = set("abcdefghijklmnñopqrstuvwxyz")
        covered = chars & alpha
        missing = alpha - chars
        return {
            "total_glyphs": len(_entries_snap),
            "unique_chars": len(chars),
            "alpha_covered": len(covered),
            "alpha_missing": sorted(missing),
            "avg_quality": round(
                sum(e.quality_score for e in _entries_snap) / max(1, len(_entries_snap)), 3
            ),
        }

    def variant_distribution(self, tier_filter: str = "") -> dict[str, int]:
        """Fase 5 — variantes por carácter en el banco (instrumentación).

        Devuelve {char: nº de instancias}. El render usa get_best_glyph(variation=
        True), que elige al azar dentro del tier: con 1 sola variante el texto sale
        idéntico repetido. Este conteo deja ver si los chars frecuentes alcanzan el
        objetivo de ≥5 variantes. tier_filter opcional ("Gold"/"Silver"/...) para
        contar solo un tier."""
        with _bank_lock:
            entries = list(self._entries)
        dist: dict[str, int] = {}
        for e in entries:
            if tier_filter and e.tier != tier_filter:
                continue
            dist[e.char] = dist.get(e.char, 0) + 1
        return dict(sorted(dist.items(), key=lambda kv: kv[1], reverse=True))

    def get_review_queue(self) -> list[GlyphEntry]:
        """Devuelve glifos que necesitan revisión (Bronze o quality < 0.50)."""
        # F7/Fase 1 — snapshot bajo lock: el hilo de fondo muta _entries y sin
        # esto se arriesga "list changed size during iteration".
        with _bank_lock:
            _entries_snap = list(self._entries)
        return [
            e for e in _entries_snap
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
        # F7/Fase 1 — snapshot bajo lock antes de agregar (no pasar la lista viva
        # a build_bank_report mientras el hilo de fondo la muta). get_review_queue
        # ya toma su propio snapshot, así que se llama fuera del with.
        with _bank_lock:
            _entries_snap = list(self._entries)
        return build_bank_report(_entries_snap, len(self.get_review_queue()))

    # Serialización movida a bank_serial.py en v4.2; estos métodos delegan ahí
    # (se conservan como wrappers para no romper callers/subclases que los usen).
    _TIER_NORMALIZE = _TIER_NORMALIZE

    def _to_dict(self, e: GlyphEntry) -> dict:
        return entry_to_dict(e)

    def _from_dict(self, d: dict) -> GlyphEntry:
        # BUG-29: normalizar tier legacy + loguear campos faltantes para diagnóstico
        return entry_from_dict(d)
