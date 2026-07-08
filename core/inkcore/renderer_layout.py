"""Layout de renglones y flujo de páginas del HandwritingRenderer (Fase R2).

Se separa de renderer.py para mantener cada módulo bajo ~420 líneas (patrón
mixin del repo). Aquí vive el corazón geométrico del render:

  • _soft_wrap_text: wrap por anchos REALES del banco (R-BUG-07) — mide cada
    palabra con la fracción nat_w/em de sus glifos, no con 0.55·font_size.
  • _render_line: selección char EXACTO antes que lower() (R-BUG-03),
    posicionamiento por BASELINE real medido (R-BUG-02) y cero descartes de
    glifos (la línea ya viene dimensionada por el wrap; un sobrante por la
    variación aleatoria invade un headroom como una mano que apura el margen).
  • _flow_blocklines_to_pages: snap de líneas base a renglones físicos.

Las firmas públicas-de-facto _render_line(text, options, max_width) y
_soft_wrap_text(text, options, usable_width) NO cambian: diagram_dsl y
concept_map las llaman directamente.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


@dataclass
class _BlockLine:
    """Un renglón ya renderizado listo para fluir en una página.

    Lo produce render_document por bloque (encabezado/lista/párrafo) y lo
    consume _flow_blocklines_to_pages, que sólo necesita saber dónde pegarlo
    en X, cuánto avanzar en Y y cuánto hueco extra dejar antes del renglón.
    """
    img: Image.Image | None
    x: int            # posición X absoluta de pegado (margen + sangría + jitter)
    line_height: int  # avance vertical de este renglón (mayor en encabezados)
    gap_before: int   # hueco extra antes del renglón (separación de bloque)
    baseline_offset: int  # px del top del renglón a su línea base (para snap a libreta)


def _connector_anchor(glyph_img, side: str, y0: int, y1: int):
    """Punto de entrada/salida del trazo de un glifo dentro de la banda
    vertical [y0, y1) (coords del glifo): la columna de tinta más externa
    del lado pedido y la fila mediana de su tinta en esa columna (R14/B).
    None si el glifo no tiene tinta en la banda (no hay dónde anclar)."""
    import numpy as np
    y0 = max(0, min(glyph_img.height - 1, y0))
    y1 = max(y0 + 1, min(glyph_img.height, y1))
    band = np.asarray(glyph_img.getchannel("A"))[y0:y1]
    cols = np.nonzero((band > 110).any(axis=0))[0]
    if len(cols) == 0:
        return None
    col = int(cols[-1] if side == "right" else cols[0])
    rows = np.nonzero(band[:, col] > 110)[0]
    return col, int(rows[len(rows) // 2]) + y0


class LayoutMixin:
    """Wrap, render de renglón y flujo de páginas. Espera self.bank y el
    estado por-render que inicializa HandwritingRenderer (_sel_history,
    _geo_overlay, _missing_chars…)."""

    # Geometría del renglón. El lienzo de un renglón mide font_size*FACTOR de alto
    # y la línea base se asienta en BASELINE_FACTOR de esa altura. Centralizados
    # para que _render_line (que dibuja) y el snap a libreta (que alinea) usen el
    # MISMO baseline; si divergen, el texto no caería sobre los renglones.
    _LINE_CANVAS_FACTOR = 2.5
    _BASELINE_FACTOR = 0.72

    @classmethod
    def _line_baseline_offset(cls, font_size: int) -> int:
        """Distancia (px) del borde superior del renglón a su línea base."""
        return int(int(font_size * cls._LINE_CANVAS_FACTOR) * cls._BASELINE_FACTOR)

    # ── Geometría por glifo (R1/R2) ──────────────────────────────────────────

    def _ensure_geometry(self) -> None:
        """Estima EN VIVO la geometría de glifos sin métricas (bancos legacy).

        El resultado vive en un overlay en memoria (no toca el manifest: eso
        es del migrador). Re-entra barato: sólo trabaja si aparecieron glifos
        nuevos sin métricas (extracción concurrente incluida).
        """
        entries = self.bank.get_all()
        # R10: ligaduras disponibles (chars de 2 letras capturados como par).
        self._pair_chars = {e.char for e in entries if len(e.char) == 2}
        attempted: set = self._geo_attempted
        pending = [e for e in entries
                   if e.metrics_source == "" and e.image_path not in attempted]
        if not pending:
            return
        attempted.update(e.image_path for e in pending)
        from core.inkcore.glyph_metrics import estimate_bank_geometry
        try:
            self._geo_overlay.update(estimate_bank_geometry(entries))
        except Exception as exc:
            logger.warning("estimación de geometría en vivo falló: %s", exc)

    def _geo(self, entry) -> dict | None:
        """Geometría efectiva de un entry: medida (manifest) o estimada (overlay)."""
        if entry is None:
            return None
        if getattr(entry, "metrics_source", ""):
            return {
                "nat_h_px": entry.nat_h_px, "nat_w_px": entry.nat_w_px,
                "baseline_off": entry.baseline_off, "em_px": entry.em_px,
                "lsb": entry.lsb, "rsb": entry.rsb,
            }
        return self._geo_overlay.get(entry.image_path)

    def _select_entry(self, ch: str):
        """Selección de variante: char EXACTO primero; lower() sólo como
        fallback registrado (R-BUG-03: antes 'A' renderizaba la 'a' aunque
        existiera 'A' en el banco)."""
        hist = getattr(self, "_sel_history", None)
        rng = getattr(self, "_sel_rng", None)
        entry = self.bank.select_glyph(ch, history=hist, rng=rng)
        if entry is None and ch.lower() != ch:
            entry = self.bank.select_glyph(ch.lower(), history=hist, rng=rng)
            if entry is not None:
                self._case_downgraded.add(ch)
        return entry

    # ── Medición de anchos (wrap real, E4) ───────────────────────────────────

    def _char_advance_frac(self, ch: str) -> float:
        """Fracción de em que avanza `ch` (ancho de tinta + gap base).

        Promedia las variantes del banco (medidas o estimadas). Cache por
        render: el banco puede crecer entre renders (extracción concurrente).
        """
        cached = self._advance_cache.get(ch)
        if cached is not None:
            return cached
        entries = self.bank.get_all(ch) or self.bank.get_all(ch.lower())
        fracs: list[float] = []
        for e in entries[:8]:
            geo = self._geo(e)
            if geo and geo["em_px"] > 0 and geo["nat_w_px"] > 0:
                fracs.append(geo["nat_w_px"] / geo["em_px"])
        # Sin datos (char faltante): estimación conservadora, ancho medio.
        frac = (sum(fracs) / len(fracs)) if fracs else 0.5
        frac = min(2.0, max(0.05, frac)) + 0.08  # + gap base entre letras
        self._advance_cache[ch] = frac
        return frac

    def _word_px(self, word: str, options) -> float:
        """Ancho esperado de una palabra en px de render."""
        return sum(self._char_advance_frac(c) for c in word) * options.font_size

    def _hyphenate(self, word: str, options, usable_width: int) -> list[str]:
        """Parte con guion simple una palabra que sola excede el ancho útil."""
        out: list[str] = []
        cur = ""
        dash = self._char_advance_frac("-") * options.font_size
        for c in word:
            if cur and self._word_px(cur + c, options) + dash > usable_width and len(cur) >= 2:
                out.append(cur + "-")
                cur = c
            else:
                cur += c
        if cur:
            out.append(cur)
        return out

    def _soft_wrap_text(
        self, text: str, options, usable_width: int,
    ) -> list[str]:
        """Wrap por palabra con anchos REALES (E4, mata R-BUG-07).

        Mide cada palabra con nat_w/em de sus glifos en vez de estimar
        0.55·font_size por char. Una palabra que no cabe baja COMPLETA; si
        sola excede el ancho, se parte con guion. Mantiene los \\n del user.
        """
        self._ensure_geometry()
        word_space = max(4.0, options.font_size
                         * getattr(options, "word_space_frac", 0.4))
        # R13 — MARGEN DERECHO IRREGULAR (opt-in): cada renglón corta en un ancho
        # un poco distinto → el borde derecho deja de ser una línea recta (unas
        # líneas se pasan un poco del margen, otras cortan antes), como la mano
        # real. RNG PROPIO sembrado de la seed (no toca el stream del layout).
        # wrap_margin_jitter=0 (default) → limit = usable_width → wrap IDÉNTICO.
        jf = max(0.0, getattr(options, "wrap_margin_jitter", 0.0))
        jit = jf * options.font_size
        if jit > 0:
            _seed = int(getattr(options, "seed", 0) or 0)
            _wrng = random.Random((_seed * 2654435761 + 0x9E37) & 0xFFFFFFFF)

            def _limit():
                return usable_width + _wrng.uniform(-jit, jit)
        else:
            def _limit():
                return usable_width
        out_lines: list[str] = []
        for raw in text.split("\n"):
            words = raw.split(" ")
            current: list[str] = []
            cur_w = 0.0
            limit = _limit()
            for w in words:
                w_px = self._word_px(w, options)
                sep = word_space if current else 0.0
                if w and w_px > usable_width:
                    # Palabra sola más ancha que el renglón: trozos con guion.
                    for piece in self._hyphenate(w, options, usable_width):
                        p_px = self._word_px(piece, options)
                        sep = word_space if current else 0.0
                        if current and cur_w + sep + p_px > limit:
                            out_lines.append(" ".join(current))
                            current, cur_w = [piece], p_px
                            limit = _limit()
                        else:
                            current.append(piece)
                            cur_w += sep + p_px
                    continue
                if current and cur_w + sep + w_px > limit:
                    out_lines.append(" ".join(current))
                    current, cur_w = [w], w_px
                    limit = _limit()
                else:
                    current.append(w)
                    cur_w += sep + w_px
            out_lines.append(" ".join(current))
        return out_lines

    def _draw_connector(self, canvas, prev, cur, options, rnd, base_y) -> None:
        """Unión procedural entre dos glifos contiguos de una palabra (R14/B).

        Traza una curva cuadrática fina del punto de SALIDA del glifo previo
        al punto de ENTRADA del actual, ambos buscados en una banda alrededor
        de la línea base (los enlaces reales salen y entran por abajo). Con
        alpha parcial: un trazo de arrastre deposita menos tinta que el
        cuerpo. Aborta en silencio si no hay anclajes o el hueco no es de
        enlace (solapado o demasiado ancho): mejor no unir que unir mal."""
        from PIL import ImageColor, ImageDraw
        (pimg, px, py), (cimg, cx, cy) = prev, cur
        fs = float(options.font_size)
        b0 = round(base_y - 0.45 * fs)
        b1 = round(base_y + 0.15 * fs)
        a_out = _connector_anchor(pimg, "right", b0 - py, b1 - py)
        a_in = _connector_anchor(cimg, "left", b0 - cy, b1 - cy)
        if a_out is None or a_in is None:
            return
        x0, y0 = px + a_out[0], py + a_out[1]
        x1, y1 = cx + a_in[0], cy + a_in[1]
        if not (2 <= x1 - x0 <= 0.4 * fs) or abs(y1 - y0) > 0.35 * fs:
            return
        # Curva con panza leve hacia abajo (el enlace natural cuelga).
        sag = rnd.uniform(0.02, 0.10) * fs
        mx, my = (x0 + x1) / 2.0, max(y0, y1) + sag
        pts = []
        for k in range(9):
            t = k / 8.0
            pts.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t * t * x1,
                        (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t * t * y1))
        try:
            r, g, b = ImageColor.getrgb(options.ink_color)[:3]
        except (ValueError, TypeError):
            r, g, b = (26, 26, 46)
        w = max(1, round(max(0.0, getattr(options, "connector_width_frac", 0.04))
                         * fs))
        # Alpha bajo deliberado (regresión tesseract R14): a 150 el enlace
        # pesa como trazo de cuerpo y el OCR fusiona letras (−4 pts); a 110
        # se lee como arrastre tenue y la caída queda dentro del margen.
        ImageDraw.Draw(canvas, "RGBA").line(pts, fill=(r, g, b, 110), width=w,
                                            joint="curve")

    # ── Render de un renglón ─────────────────────────────────────────────────

    def _render_line(self, text: str, options, max_width: int) -> Image.Image | None:
        if not PIL_OK:
            return None
        if not text.strip():
            return None
        # El lienzo reserva headroom vertical para astas/colas y un headroom
        # horizontal de ~1.5 em: el wrap dimensiona con anchos nominales y la
        # variación aleatoria puede pasar el borde unos px — se pinta (una mano
        # también apura el margen) en vez de DESCARTAR glifos (R-BUG-07).
        h = int(options.font_size * self._LINE_CANVAS_FACTOR)
        headroom = int(options.font_size * 1.5)
        line_canvas = Image.new("RGBA", (max_width + headroom, h), (0, 0, 0, 0))
        x_cursor = 0

        from core.inkcore.renderer_noise import OUProcess, tnorm
        rnd = getattr(self, "_rng", None) or random.Random()

        # R14 (Track A): avanza el latente de mano e(t) — estado LENTO por
        # página que acopla tamaño, slant, presión y ritmo. hand_on gatea
        # todos los acoples (apagado ⇒ cero draws, byte-idéntico).
        self._hand_energy_step(options)
        hand_on = getattr(self, "_hand_walk", None) is not None
        # R18 — avanza el contador de renglón global y evalúa la fatiga del doc.
        self._doc_line = getattr(self, "_doc_line", 0) + 1
        fat = self._fatigue_at(options)

        # R3 — inclinación BASE del renglón: proceso OU ENTRE líneas (la mano
        # hereda el ángulo del renglón anterior y deriva; antes era i.i.d.).
        line_slant_amp = max(0.0, getattr(options, "line_slant_deg", 0.0))
        if line_slant_amp > 0:
            walk = self._line_slant_walk
            if walk is None or walk.bound != line_slant_amp:
                walk = OUProcess(rnd, sigma=line_slant_amp * 0.4, rho=0.9,
                                 bound=line_slant_amp)
                self._line_slant_walk = walk
            self._cur_line_slant = walk.step()
            if hand_on:
                # R14 (Track A): el slant de línea COMPARTE el latente — la
                # misma "energía" que agranda/presiona también recuesta la
                # mano, en vez de correr como proceso independiente. Aporta
                # hasta ±0.35·amp·1.5σ encima del OU acotado.
                self._cur_line_slant += 0.35 * line_slant_amp * self._hand_e
        else:
            self._cur_line_slant = 0.0
        self._last_line_slants.append(self._cur_line_slant)

        self._ensure_geometry()
        # R4: fracciones calibrables desde la página patrón del usuario
        # (RenderOptions.from_calibration); defaults = comportamiento previo.
        word_space_base = max(4.0, options.font_size
                              * getattr(options, "word_space_frac", 0.4))
        ws_cv = max(0.0, getattr(options, "word_space_cv", 0.18))
        spacing_gap_base = max(2, int(options.font_size
                                      * getattr(options, "letter_gap_frac", 0.08)))
        kj = max(0.0, min(1.0, options.kerning_jitter))
        # Jitter vertical por glifo: OU sutil (≤±2px) — el temblor blanco por
        # letra mataba la autocorrelación del baseline (tell #9).
        vjit = min(2, max(0, options.jitter_px))
        y_walk = OUProcess(rnd, sigma=vjit * 0.4, rho=0.75, bound=vjit) if vjit else None

        # Deriva de línea base: OU acotado a lo largo del renglón. ρ alto: el
        # vaivén es de MUÑECA (decenas de letras), no de dedo.
        drift_amp = max(0.0, options.baseline_drift)
        drift_walk = OUProcess(rnd, sigma=drift_amp * 0.35, rho=0.95,
                               bound=drift_amp) if drift_amp > 0 else None
        base_y = int(h * self._BASELINE_FACTOR)

        # R3 — rotación por glifo CORRELACIONADA: la muñeca deriva a lo largo
        # del renglón (OU), no tirita (ruido blanco ±rotation_range = "texto
        # borracho"). rotation_range pasa a ser la AMPLITUD del proceso.
        rot_amp = max(0.0, options.rotation_range)
        rot_walk = OUProcess(rnd, sigma=rot_amp * 0.3, rho=0.85,
                             bound=rot_amp) if rot_amp > 0 else None
        # R5 (C1) — tamaño y slant por glifo también DERIVAN (OU intra-renglón)
        # en vez de sortearse i.i.d.: la mano que venía escribiendo chico sigue
        # chico unas letras más.
        sv = max(0.0, options.size_variation)
        size_walk = OUProcess(rnd, sigma=sv * 0.25, rho=0.88,
                              bound=sv * 0.8) if sv > 0 else None
        sl_amp = max(0.0, getattr(options, "glyph_slant_drift_deg", 1.0))
        slant_walk = OUProcess(rnd, sigma=sl_amp * 0.3, rho=0.85,
                               bound=sl_amp) if sl_amp > 0 else None

        # R14 (Track A) — acoples del latente e(t) y cramping de fin de
        # renglón. squeeze(): factor de compresión de gaps/espacios en el
        # último ~18% del ancho (una mano aprieta al ver venir el margen);
        # rhythm: el espacio de palabra respira con e(t). Con los knobs en 0
        # ambos factores son EXACTAMENTE 1.0 y no hay draws extra.
        cramp = min(0.3, max(0.0, getattr(options, "line_end_cramp", 0.0)))
        pd = min(0.4, max(0.0, getattr(options, "pressure_darkness_coupling", 0.0)))
        # R14 (Track B) — uniones procedurales entre glifos de una palabra.
        # prev_glyph = (img, x, y) del glifo anterior; se corta en cada
        # palabra nueva y en glifos faltantes (nada que unir con un
        # placeholder). conn_p=0 (default) ⇒ cero draws, byte-idéntico.
        conn_p = min(0.7, max(0.0, getattr(options, "connector_prob", 0.0)))
        prev_glyph = None

        def _squeeze() -> float:
            if cramp <= 0 or max_width <= 0:
                return 1.0
            rem = 1.0 - min(1.0, x_cursor / max_width)
            if rem >= 0.18:
                return 1.0
            return 1.0 - cramp * (1.0 - rem / 0.18)

        first_word = True
        for word in text.split(" "):
            if word == "":
                if not first_word:
                    rhythm = 1.0 + 0.18 * self._hand_energy_at(
                        x_cursor / max_width) if hand_on else 1.0
                    x_cursor += round(tnorm(rnd, word_space_base, word_space_base * ws_cv,
                                            word_space_base * 0.5, word_space_base * 2.2)
                                      * rhythm * _squeeze())
                continue
            if not first_word:
                # E1: espacio de palabra VARIABLE (gauss truncada) — era
                # constante (R-BUG-05, tell #3). R14: modulada por e(t) y
                # comprimida al final del renglón.
                rhythm = 1.0 + 0.18 * self._hand_energy_at(
                    x_cursor / max_width) if hand_on else 1.0
                x_cursor += round(tnorm(rnd, word_space_base, word_space_base * ws_cv,
                                        word_space_base * 0.5, word_space_base * 2.2)
                                  * rhythm * _squeeze())
            first_word = False

            # R10 (G3): lookup de LIGADURA antes que de char suelto. Si el
            # banco tiene el par ("qu", "ll"…) se usa con probabilidad
            # ligature_prob — una mano liga unas veces sí y otras no.
            lig_p = max(0.0, min(1.0, getattr(options, "ligature_prob", 0.0)))
            pairs = getattr(self, "_pair_chars", set())
            prev_glyph = None   # R14/B: los enlaces no cruzan espacios
            idx = 0
            while idx < len(word):
                par = word[idx:idx + 2]
                if (len(par) == 2 and lig_p > 0 and par in pairs
                        and rnd.random() < lig_p):
                    ch = par
                else:
                    ch = word[idx]
                idx += len(ch)
                entry = self._select_entry(ch)
                baseline_in = -1
                # R14 (Track A): e(t) evaluado en la posición del glifo y el
                # squeeze de fin de renglón. Con el latente apagado e_now=0 y
                # sq=1.0: los argumentos de _load_glyph quedan idénticos.
                e_now = (self._hand_energy_at(x_cursor / max_width)
                         if hand_on else 0.0)
                sq = _squeeze()
                # R17 — presión i.i.d. por glifo (rápida, no correlacionada);
                # RNG sólo si la perilla está activa (byte-idéntico con 0).
                gpj = getattr(options, "glyph_pressure_jitter", 0.0)
                press_iid = (tnorm(rnd, 0.0, gpj, -2.2 * gpj, 2.2 * gpj)
                             if gpj > 0 else 0.0)
                # R18 — fatiga acoplada al glifo: tamaño crece y se afloja,
                # slant deriva hacia UN lado y tiembla más, presión se vuelve
                # errática y un pelo más floja. Draws SOLO si hay fatiga.
                # Umbral 0.10: por debajo (textos cortos, ~<7 renglones) la
                # fatiga NO consume RNG → byte-idéntica a fatiga-off, protege el
                # gate de legibilidad y no perturba la selección de variantes.
                fat_size = fat_slant = fat_press = 0.0
                if fat > 0.10:
                    fat_size = (0.12 * fat
                                + tnorm(rnd, 0.0, 0.10 * fat, -0.28 * fat, 0.28 * fat))
                    fat_slant = (4.0 * fat * self._fatigue_slant_dir
                                 + tnorm(rnd, 0.0, 2.2 * fat, -5.5 * fat, 5.5 * fat))
                    fat_press = (-0.07 * fat
                                 + tnorm(rnd, 0.0, 0.18 * fat, -0.42 * fat, 0.42 * fat))
                if entry and Path(entry.image_path).exists():
                    loaded = self._load_glyph(
                        entry.image_path, options, ch, geo=self._geo(entry),
                        rotation=(rot_walk.step() if rot_walk else 0.0) + fat_slant,
                        rng=rnd,
                        size_drift=(size_walk.step() if size_walk else 0.0)
                                   + 0.08 * e_now - 0.4 * (1.0 - sq) + fat_size,
                        slant_extra=(slant_walk.step() if slant_walk else 0.0)
                                    + 0.3 * sl_amp * e_now,
                        pressure=(pd * e_now if (hand_on and pd > 0) else 0.0)
                                 + press_iid + fat_press)
                    glyph_img, baseline_in = loaded if loaded else (None, -1)
                else:
                    # R3/H8 — glifo faltante: se registra para que la UI avise
                    # antes de exportar. NUNCA se omite en silencio: un char sin
                    # glifo deja SIEMPRE una marca VISIBLE (placeholder rojo
                    # subrayado), aunque allow_font_fallback=False (export real).
                    # Así "subió" no se vuelve "subi" sin dejar rastro.
                    if not ch.isspace():
                        self._missing_chars.add(ch)
                        glyph_img = self._render_fallback_char(
                            ch, options, missing=True)
                    else:
                        glyph_img = None
                    prev_glyph = None   # R14/B: no unir con un placeholder
                if glyph_img is None:
                    continue

                gap = spacing_gap_base
                if kj > 0:
                    # R2: el jitter puede dejar gap NEGATIVO leve (las letras
                    # de una palabra real se rozan); R3: gauss truncada.
                    gap += round(tnorm(rnd, -spacing_gap_base * kj * 0.5,
                                       spacing_gap_base * kj * 0.6,
                                       -spacing_gap_base * (1 + kj),
                                       spacing_gap_base * kj))
                    gap = max(-int(options.font_size * 0.06), gap)
                else:
                    gap = max(1, gap)
                if sq < 1.0:
                    # R14 (Track A): cramping — los huecos se encogen
                    # progresivamente al acercarse al margen derecho.
                    gap = round(gap * sq)

                jitter_y = round(y_walk.step()) if y_walk else 0
                drift = drift_walk.step() if drift_walk else 0.0
                baseline = base_y + round(drift)
                if baseline_in >= 0:
                    # R2: posición por BASELINE REAL — la fila medida del glifo
                    # cae exacto sobre la línea base del renglón (R-BUG-02).
                    y_pos = baseline - baseline_in
                else:
                    # Sin métricas ni estimación: clase vertical legacy.
                    if self._vertical_class(ch) == "desc":
                        y_pos = baseline - int(glyph_img.height * 0.69)
                    else:
                        y_pos = baseline - glyph_img.height
                y_pos = max(0, min(h - glyph_img.height, y_pos + jitter_y))
                line_canvas.paste(glyph_img, (x_cursor, y_pos), glyph_img)
                if conn_p > 0:
                    # R14 (Track B): con prob conn_p, trazo fino de enlace
                    # entre el glifo anterior y éste (misma palabra).
                    if prev_glyph is not None and rnd.random() < conn_p:
                        self._draw_connector(line_canvas, prev_glyph,
                                             (glyph_img, x_cursor, y_pos),
                                             options, rnd, baseline)
                    prev_glyph = (glyph_img, x_cursor, y_pos)
                self._glyphs_placed += len(ch)  # una ligadura cubre 2 chars
                x_cursor += glyph_img.width + gap

        return line_canvas

    # ── Flujo de renglones a páginas ─────────────────────────────────────────

    def _flow_blocklines_to_pages(
        self, items: list, options, page_height: int, base_line_h: int,
    ) -> list:
        """Reparte los renglones ya renderizados en páginas de altura fija.

        Mantiene un cursor vertical, abre página nueva cuando un renglón no entra y
        nunca pega por encima del margen ni fuera de la hoja.

        SNAP A RENGLÓN FÍSICO: salvo en cuadrícula, cada renglón se ALINEA para
        que su línea base caiga EXACTO sobre un renglón de la hoja
        (margin_top + k·base_line_h). Aplica también con fondo "hoja blanca":
        el usuario imprime sobre una hoja con renglones REALES aunque el render
        no los dibuje. Redondea al renglón MÁS CERCANO (no ceil): el
        lienzo de un renglón reserva headroom mayor que base_line_h, así que un ceil
        saltaría un renglón y dejaría el primero vacío. Una guarda de no-solape
        (next_min_k) impide que un renglón caiga sobre el anterior, reservando los
        renglones de grilla que ocupa cada línea (clave tras un encabezado alto).
        Para renglones de cuerpo consecutivos el snap es transparente. El jitter
        horizontal y la micro-rotación se conservan: el "hecho a mano" queda en X.
        """
        from core.inkcore.renderer_backgrounds import BACKGROUND_STYLES

        bottom = page_height - options.margin_bottom_px
        margin = options.margin_top_px
        # Paso de grilla FLOTANTE: las posiciones se calculan round(k·sf) para
        # que el redondeo del paso no acumule desfase a lo largo de la hoja.
        sf = options.line_spacing_px
        style_def = BACKGROUND_STYLES.get(options.background_style, {})
        snap = base_line_h > 0 and not style_def.get("draw_grid")

        def _grid_y(k: int) -> int:
            """Y de la línea base del renglón físico k (1=primero)."""
            return margin + round(k * sf)

        def _new_canvas():
            # R6 (I2): capa de TINTA transparente; papel/decoraciones se
            # aplican al cerrar la página (_compose_page, multiply).
            return Image.new("RGBA", (options.page_width, page_height), (0, 0, 0, 0))

        def _snap_k(y_top: int, it, floor_k: int) -> int:
            """Índice del renglón de grilla (1=primero) que recibe la línea base."""
            desired = y_top + it.baseline_offset
            k = round((desired - margin) / sf)
            return max(1, floor_k, k)

        pages = []
        canvas = _new_canvas()
        y = margin
        next_min_k = 1
        for it in items:
            y += max(0, it.gap_before)
            do_snap = snap and it.baseline_offset > 0
            if do_snap:
                k = _snap_k(y, it, next_min_k)
                paste_y = _grid_y(k) - it.baseline_offset
            else:
                k = None
                paste_y = y
            # ¿Cabe este renglón? Si no, cierra la página y re-snapea arriba.
            if it.line_height > 0 and paste_y + it.line_height > bottom and y > margin:
                pages.append(self._compose_page(canvas, options, sf, page_height))
                canvas = _new_canvas()
                y = margin
                next_min_k = 1
                if do_snap:
                    k = _snap_k(y, it, next_min_k)
                    paste_y = _grid_y(k) - it.baseline_offset
                else:
                    paste_y = y
            if it.img is not None:
                x = max(0, it.x)
                py = max(0, min(page_height - it.img.height, paste_y))
                canvas.paste(it.img, (x, py), it.img)
            if k is not None:
                # Reservar los renglones de grilla que ocupa esta línea (ceil).
                # ceil con epsilon: line_height_px se REDONDEA desde mm (89 a
                # 300 DPI) y puede quedar un pelo arriba del paso flotante
                # (88.58) — sin tolerancia, ceil(89/88.58)=2 reservaría un
                # renglón de más y el cuerpo saltaría renglones alternados.
                span = max(1, int(-(-(it.line_height - 0.5) // sf)))
                next_min_k = k + span
            # El cursor continuo sigue desde la base de este renglón para que el
            # siguiente caiga un renglón más abajo (snap transparente en el cuerpo).
            y = paste_y + it.line_height

        pages.append(self._compose_page(canvas, options, sf, page_height))
        return pages
