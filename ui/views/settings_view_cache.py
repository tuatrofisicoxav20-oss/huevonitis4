"""SettingsCacheMixin — sección de caché OCR en Settings."""
import customtkinter as ctk

import config
from ui import theme


class SettingsCacheMixin:
    """Sección de caché OCR: muestra tamaño/entradas y permite limpiar."""

    def _build_cache_section(self, parent):
        card = self.card_frame(parent)
        card.pack(fill="x", pady=8)

        ctk.CTkLabel(card, text="🗄️ Caché OCR", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 4))

        self._cache_size_label = ctk.CTkLabel(
            card, text=self._get_cache_size_text(),
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
        )
        self._cache_size_label.pack(anchor="w", padx=16, pady=4)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=16, pady=(4, 12))

        self.secondary_button(row, "🔄 Actualizar",
                              self._refresh_cache_size, 120).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="🗑 Limpiar caché", width=140,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_BODY, command=self._clear_cache,
        ).pack(side="left")

        ctk.CTkFrame(card, height=1, fg_color=theme.BORDER).pack(fill="x", padx=12, pady=(4, 0))

    def _get_cache_size_text(self) -> str:
        try:
            from core.ocr.result_cache import OCRResultCache
            cache = OCRResultCache()
            mb = cache.cache_size_mb()
            count = (len(list(config.OCR_CACHE_DIR.glob("*.pkl")))
                     if config.OCR_CACHE_DIR.exists() else 0)
            return f"Tamaño: {mb:.2f} MB  |  Entradas: {count}"
        except Exception:
            return "Caché OCR no disponible"

    def _refresh_cache_size(self):
        self._cache_size_label.configure(text=self._get_cache_size_text())

    def _clear_cache(self):
        try:
            from core.ocr.result_cache import OCRResultCache
            removed = OCRResultCache().clear()
            self._cache_size_label.configure(text=self._get_cache_size_text())
            self.toast(f"Caché limpiada ({removed} entradas)", "success")
        except Exception as exc:
            self.toast(f"Error al limpiar caché: {exc}", "error")
