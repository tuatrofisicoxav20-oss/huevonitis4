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
    img: "Image.Image | None"
    x: int            # posición X absoluta de pegado (margen + sangría + jitter)
    line_height: int  # avance vertical de este renglón (mayor en encabezados)
    gap_before: int   # hueco extra antes del renglón (separación de bloque)
    baseline_offset: int  # px del top del renglón a su línea base (para snap a libreta)


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

    def _geo(self, entry) -> "dict | None":
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
        out_lines: list[str] = []
        for raw in text.split("\n"):
            words = raw.split(" ")
            current: list[str] = []
            cur_w = 0.0
            for w in words:
                w_px = self._word_px(w, options)
                sep = word_space if current else 0.0
                if w and w_px > usable_width:
                    # Palabra sola más ancha que el renglón: trozos con guion.
                    for piece in self._hyphenate(w, options, usable_width):
                        p_px = self._word_px(piece, options)
                        sep = word_space if current else 0.0
                        if current and cur_w + sep + p_px > usable_width:
                            out_lines.append(" ".join(current))
                            current, cur_w = [piece], p_px
                        else:
                            current.append(piece)
                            cur_w += sep + p_px
                    continue
                if current and cur_w + sep + w_px > usable_width:
                    out_lines.append(" ".join(current))
                    current, cur_w = [w], w_px
                else:
                    current.append(w)
                    cur_w += sep + w_px
            out_lines.append(" ".join(current))
        return out_lines

    # ── Render de un renglón ─────────────────────────────────────────────────

    def _render_line(self, text: str, options, max_width: int) -> "Image.Image | None":
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

        first_word = True
        for word in text.split(" "):
            if word == "":
                if not first_word:
                    x_cursor += round(tnorm(rnd, word_space_base, word_space_base * ws_cv,
                                            word_space_base * 0.5, word_space_base * 2.2))
                continue
            if not first_word:
                # E1: espacio de palabra VARIABLE (gauss truncada) — era
                # constante (R-BUG-05, tell #3).
                x_cursor += round(tnorm(rnd, word_space_base, word_space_base * ws_cv,
                                        word_space_base * 0.5, word_space_base * 2.2))
            first_word = False

            for ch in word:
                entry = self._select_entry(ch)
                baseline_in = -1
                if entry and Path(entry.image_path).exists():
                    loaded = self._load_glyph(
                        entry.image_path, options, ch, geo=self._geo(entry),
                        rotation=rot_walk.step() if rot_walk else 0.0, rng=rnd)
                    glyph_img, baseline_in = loaded if loaded else (None, -1)
                else:
                    # R3/H8 — glifo faltante: se OMITE y se registra (la UI
                    # avisa antes de exportar). El placeholder de fuente de
                    # sistema sólo con allow_font_fallback=True (preview).
                    if not ch.isspace():
                        self._missing_chars.add(ch)
                    glyph_img = (
                        self._render_fallback_char(ch, options, missing=True)
                        if getattr(options, "allow_font_fallback", False) else None
                    )
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
                self._glyphs_placed += 1
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
            c = Image.new("RGBA", (options.page_width, page_height), options.background_color)
            self._draw_background_decorations(c, options, sf, page_height)
            return c

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
                pages.append(canvas.convert("RGB"))
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
                span = max(1, int(-(-it.line_height // sf)))
                next_min_k = k + span
            # El cursor continuo sigue desde la base de este renglón para que el
            # siguiente caiga un renglón más abajo (snap transparente en el cuerpo).
            y = paste_y + it.line_height

        pages.append(canvas.convert("RGB"))
        return pages
