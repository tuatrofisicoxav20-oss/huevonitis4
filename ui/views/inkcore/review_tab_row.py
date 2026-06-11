"""ReviewTabRowMixin — render de filas + modal rename del Review tab.

Separado de review_tab.py. Depende de:
  • self._review_scroll, self._review_check_vars, self._review_checkboxes
  • self._get_thumb, self._pipeline.bank
  • self._reload_and_refresh_all, self.toast
"""
import customtkinter as ctk

from ui import theme
from ui.modal_utils import safe_grab


class ReviewTabRowMixin:
    """Construcción de filas de revisión + modal para renombrar."""

    def _build_review_row(self, glyph):
        tier_color = theme.TIER_COLORS.get(glyph.tier, "#888")

        row = ctk.CTkFrame(
            self._review_scroll,
            fg_color=theme.CARD_BG,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        # anchor (no fill): la fila estirada se redibuja con cada cambio
        # de ancho del scrollable → O(N²) de redraws al construir.
        row.pack(anchor="w", padx=2, pady=3)

        var = ctk.BooleanVar(value=False)
        self._review_check_vars.append(var)
        cb = ctk.CTkCheckBox(
            row, text="", variable=var, width=30,
            checkbox_width=18, checkbox_height=18,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
        )
        cb.pack(side="left", padx=(8, 4), pady=8)
        self._review_checkboxes.append((cb, glyph))

        img_frame = ctk.CTkFrame(
            row, width=64, height=64,
            fg_color="#000000",
            corner_radius=6,
            border_width=2,
            border_color=tier_color,
        )
        img_frame.pack(side="left", padx=4, pady=8)
        img_frame.pack_propagate(False)

        photo = self._get_thumb(glyph.image_path, 56, 56)
        if photo is not None:
            ctk.CTkLabel(img_frame, image=photo, text="").place(relx=0.5, rely=0.5, anchor="center")
        else:
            ctk.CTkLabel(img_frame, text="?", font=("Segoe UI", 20),
                         text_color=theme.TEXT_MUTED).place(relx=0.5, rely=0.5, anchor="center")

        char_frame = ctk.CTkFrame(row, fg_color="transparent", width=80)
        char_frame.pack(side="left", padx=4, pady=8)
        char_frame.pack_propagate(False)
        ctk.CTkLabel(
            char_frame,
            text=glyph.char or "?",
            font=("Segoe UI", 22, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack()
        ctk.CTkButton(
            char_frame, text="✏️", width=28, height=22,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=("Segoe UI", 10),
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack()

        q = glyph.quality_score
        if q >= 0.75:
            bar_color = theme.ACCENT_GREEN
        elif q >= 0.50:
            bar_color = theme.ACCENT_ORANGE
        else:
            bar_color = theme.ACCENT_RED

        q_frame = ctk.CTkFrame(row, fg_color="transparent", width=140)
        q_frame.pack(side="left", padx=4, pady=8)
        q_frame.pack_propagate(False)
        bar = ctk.CTkProgressBar(
            q_frame, width=120, height=10,
            fg_color=theme.BG_TERTIARY,
            progress_color=bar_color,
            corner_radius=4,
        )
        bar.set(max(0.0, min(1.0, q)))
        bar.pack(pady=(6, 0))
        ctk.CTkLabel(q_frame, text=f"{q:.0%}",
                     font=("Segoe UI", 9), text_color=bar_color).pack()

        score_frame = ctk.CTkFrame(row, fg_color="transparent", width=100)
        score_frame.pack(side="left", padx=4, pady=8)
        score_frame.pack_propagate(False)
        ctk.CTkLabel(score_frame, text=f"{q:.3f}",
                     font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack()
        tier_bg = theme.TIER_BG.get(glyph.tier, theme.CARD_BG)
        ctk.CTkLabel(
            score_frame, text=glyph.tier,
            font=("Segoe UI", 9, "bold"),
            text_color=tier_color, fg_color=tier_bg,
            corner_radius=8, padx=6, pady=2,
        ).pack(pady=2)

        flags_frame = ctk.CTkFrame(row, fg_color="transparent", width=180)
        flags_frame.pack(side="left", padx=4, pady=8)
        flags_frame.pack_propagate(False)
        flags = []
        if glyph.quality_score < 0.50:
            flags.append("low_quality")
        if glyph.tier == "Bronze":
            flags.append("bronze_tier")
        if glyph.ink_coverage < 0.05:
            flags.append("tinta_escasa")
        for flag in flags[:3]:
            ctk.CTkLabel(
                flags_frame, text=flag.replace("_", " "),
                font=("Segoe UI", 8),
                text_color=theme.ACCENT_ORANGE,
                fg_color=theme.BADGE_BG_ORANGE,
                corner_radius=6, padx=5, pady=1,
            ).pack(side="top", anchor="w", pady=1)

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=8, pady=8)

        for txt, fg, hover, cmd in [
            ("⬆️", theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER,
             lambda g=glyph: self._review_promote(g)),
            ("❌", theme.ACCENT_RED, theme.ACCENT_RED_HOVER,
             lambda g=glyph: self._review_reject(g)),
            ("🔄", theme.ACCENT_BLUE, theme.ACCENT_BLUE_HOVER,
             lambda g=glyph: self._open_rename_modal(g)),
        ]:
            ctk.CTkButton(
                btn_frame, text=txt, width=36, height=30,
                fg_color=fg, hover_color=hover,
                font=("Segoe UI", 14), corner_radius=8,
                command=cmd,
            ).pack(side="left", padx=2)

    def _open_rename_modal(self, glyph):
        win = ctk.CTkToplevel(self)
        win.title("Cambiar carácter")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("360x280")
        safe_grab(win, self)
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text="Cambiar letra del glifo",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        preview_row = ctk.CTkFrame(win, fg_color="transparent")
        preview_row.pack(pady=8)

        ctk.CTkLabel(
            preview_row, text=f"Actual: '{glyph.char}'",
            font=("Segoe UI", 14, "bold"), text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=16)
        ctk.CTkLabel(preview_row, text="→",
                     font=("Segoe UI", 16), text_color=theme.TEXT_MUTED).pack(side="left")
        new_char_preview = ctk.CTkLabel(
            preview_row, text="?",
            font=("Segoe UI", 18, "bold"), text_color=theme.ACCENT_ORANGE,
        )
        new_char_preview.pack(side="left", padx=16)

        ctk.CTkLabel(
            win, text="Nuevo carácter:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=24, pady=(4, 0))

        entry = ctk.CTkEntry(
            win, width=200, height=36,
            font=("Segoe UI", 18),
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
            justify="center",
        )
        entry.pack(padx=24, pady=(2, 8))
        entry.focus_set()

        def on_key(*_):
            val = entry.get().strip()
            new_char_preview.configure(text=val[:1] if val else "?")

        entry.bind("<KeyRelease>", on_key)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=8)

        def _save():
            new_char = entry.get().strip()
            if not new_char:
                return
            self._pipeline.bank.rename_glyph(glyph, new_char[:1])
            self.toast(f"'{glyph.char}' renombrado a '{new_char[:1]}'", "success")
            win.destroy()
            self._reload_and_refresh_all()

        ctk.CTkButton(
            btn_row, text="Guardar",
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            height=34, width=110,
            command=_save,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row, text="Cancelar",
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            height=34, width=90,
            command=win.destroy,
        ).pack(side="left", padx=4)

        entry.bind("<Return>", lambda e: _save())
