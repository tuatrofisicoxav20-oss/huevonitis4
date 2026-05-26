"""BusinessView — vista principal del módulo de negocio (trabajos, pagos, dashboard).

La lógica está en mixins:
  • BusinessJobsMixin      — trabajos + cotizaciones
  • BusinessPaymentsMixin  — registro de pagos
  • BusinessDashboardMixin — KPIs + chart
"""
import contextlib
import tkinter as tk

import customtkinter as ctk

from core.businesscore.ledger import BusinessLedger
from core.businesscore.models import ClientJob
from ui import theme
from ui.views.base_view import BaseView
from ui.views.business_view_dashboard import BusinessDashboardMixin
from ui.views.business_view_jobs import BusinessJobsMixin
from ui.views.business_view_payments import BusinessPaymentsMixin


class BusinessView(
    BusinessJobsMixin,
    BusinessPaymentsMixin,
    BusinessDashboardMixin,
    BaseView,
):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._ledger: BusinessLedger = app.ledger
        self._selected_job: ClientJob | None = None
        self._pie_anim_job = None
        self._build()

    def _build(self):
        self._tabs = ctk.CTkTabview(
            self, fg_color="transparent",
            segmented_button_fg_color=theme.BG_TERTIARY,
            segmented_button_selected_color=theme.ACCENT_BLUE,
            segmented_button_unselected_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
        )
        self._tabs.pack(fill="both", expand=True, padx=16, pady=16)
        self._tabs.add("💼 Trabajos")
        self._tabs.add("📋 Cotizaciones")
        self._tabs.add("💰 Pagos")
        self._tabs.add("📊 Dashboard")

        self._build_jobs_tab(self._tabs.tab("💼 Trabajos"))
        self._build_quotes_tab(self._tabs.tab("📋 Cotizaciones"))
        self._build_payments_tab(self._tabs.tab("💰 Pagos"))
        self._build_dashboard_tab(self._tabs.tab("📊 Dashboard"))

    def _build_jobs_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(top, text="Trabajos de Clientes", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")
        self.primary_button(top, "+ Nuevo Trabajo", self._new_job_dialog, 130).pack(side="right")

        self._jobs_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._jobs_scroll.pack(fill="both", expand=True, padx=4)

    def _build_quotes_tab(self, parent):
        ctk.CTkLabel(parent, text="Cotización", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=12, pady=12)

        self._quote_card = self.card_frame(parent)
        self._quote_card.pack(fill="both", expand=True, padx=8)

        self._quote_info = ctk.CTkLabel(
            self._quote_card,
            text="Selecciona un trabajo en la pestaña 'Trabajos' para ver la cotización",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            wraplength=500, justify="center",
        )
        self._quote_info.place(relx=0.5, rely=0.5, anchor="center")

    def _build_payments_tab(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(top, text="Registro de Pagos", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")
        self.primary_button(top, "+ Registrar Pago", self._new_payment_dialog, 140).pack(side="right")

        self._totals_frame = ctk.CTkFrame(parent, fg_color=theme.CARD_BG, corner_radius=10)
        self._totals_frame.pack(fill="x", padx=8, pady=(0, 10))
        self._totals_label = ctk.CTkLabel(self._totals_frame, text="",
                                          font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY)
        self._totals_label.pack(padx=16, pady=10)

        self._payments_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._payments_scroll.pack(fill="both", expand=True, padx=4)

    def _build_dashboard_tab(self, parent):
        ctk.CTkLabel(parent, text="Dashboard de Negocio", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=12, pady=(12, 8))

        cards_row = ctk.CTkFrame(parent, fg_color="transparent")
        cards_row.pack(fill="x", padx=8, pady=(0, 12))
        self._dash_cards: list = []
        for title, color in [("Total Ingresos", theme.ACCENT_GREEN),
                             ("Trabajos Activos", theme.ACCENT_ORANGE),
                             ("Pendiente Cobro", theme.ACCENT_BLUE)]:
            card = self.card_frame(cards_row)
            card.pack(side="left", expand=True, fill="x", padx=6, ipady=10)
            ctk.CTkLabel(card, text=title, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(padx=12, pady=(10, 2), anchor="w")
            val_lbl = ctk.CTkLabel(card, text="$0", font=("Segoe UI", 20, "bold"),
                                   text_color=color)
            val_lbl.pack(padx=12, anchor="w", pady=(0, 10))
            self._dash_cards.append(val_lbl)

        chart_frame = self.card_frame(parent)
        chart_frame.pack(fill="both", expand=True, padx=8)
        ctk.CTkLabel(chart_frame, text="Estado de Trabajos", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=14, pady=(12, 6))

        self._chart_canvas = tk.Canvas(chart_frame, bg=theme.CARD_BG,
                                       highlightthickness=0, height=200)
        self._chart_canvas.pack(fill="x", padx=12, pady=(0, 12))

    def on_hide(self):
        if self._pie_anim_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._pie_anim_job)
            self._pie_anim_job = None

    def on_show(self):
        self._refresh_jobs()
        self._refresh_payments()
        self._refresh_dashboard()
