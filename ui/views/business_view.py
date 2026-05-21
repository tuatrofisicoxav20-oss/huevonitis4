import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

import config
from core.businesscore.estimator import calculate_price, generate_whatsapp_message, get_price_breakdown
from core.businesscore.ledger import BusinessLedger
from core.businesscore.models import JOB_STATUSES, JOB_TYPES, STATUS_COLORS, URGENCIES, ClientJob, Payment
from ui import theme
from ui.animations import count_up
from ui.views.base_view import BaseView


class BusinessView(BaseView):
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

        self._quote_info = ctk.CTkLabel(self._quote_card,
                                        text="Selecciona un trabajo en la pestaña 'Trabajos' para ver la cotización",
                                        font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
                                        wraplength=500, justify="center")
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

        self._chart_canvas = tk.Canvas(chart_frame, bg=theme.CARD_BG, highlightthickness=0, height=200)
        self._chart_canvas.pack(fill="x", padx=12, pady=(0, 12))

    def _refresh_jobs(self):
        for w in self._jobs_scroll.winfo_children():
            w.destroy()
        jobs = self._ledger.get_jobs()
        if not jobs:
            ctk.CTkLabel(self._jobs_scroll, text="No hay trabajos. Crea uno con '+ Nuevo Trabajo'",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=30)
            return
        for job in reversed(jobs):
            self._make_job_card(job)

    def _make_job_card(self, job: ClientJob):
        card = ctk.CTkFrame(self._jobs_scroll, fg_color=theme.CARD_BG,
                            corner_radius=10, border_width=1,
                            border_color=theme.BORDER, cursor="hand2")
        card.bind("<Enter>", lambda e: card.configure(
            fg_color=theme.CARD_BG_HOVER, border_color=theme.BORDER_LIGHT), add="+")
        card.bind("<Leave>", lambda e: card.configure(
            fg_color=theme.CARD_BG, border_color=theme.BORDER), add="+")
        card.pack(fill="x", pady=4)
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(row1, text=job.client_name or "Sin nombre", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")

        status_color = STATUS_COLORS.get(job.status, "#888")
        badge = ctk.CTkFrame(row1, fg_color=status_color, corner_radius=12)
        badge.pack(side="right")
        ctk.CTkLabel(badge, text=f" {job.status} ", font=theme.FONT_SMALL,
                     text_color="white").pack(padx=6, pady=2)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(row2, text=f"{job.job_type} • {job.pages} pág • {job.urgency}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(side="left")
        if job.price_mxn > 0:
            ctk.CTkLabel(row2, text=f"${job.price_mxn:,.2f} MXN",
                         font=("Segoe UI", 12, "bold"),
                         text_color=theme.ACCENT_GREEN).pack(side="right")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 8))

        for label, cmd_fn, color in [
            ("Ver Cotización", lambda j=job: self._show_quote(j), theme.ACCENT_BLUE),
            ("Cambiar Estado", lambda j=job: self._change_status_dialog(j), theme.ACCENT_ORANGE),
            ("Eliminar", lambda j=job: self._delete_job(j), theme.ACCENT_RED),
        ]:
            ctk.CTkButton(btn_row, text=label, width=110, height=28,
                          fg_color=color, font=theme.FONT_SMALL,
                          command=cmd_fn).pack(side="left", padx=4)

        card.bind("<Button-1>", lambda e, j=job: self._select_job(j))

    def _select_job(self, job: ClientJob):
        self._selected_job = job

    def _show_quote(self, job: ClientJob):
        self._selected_job = job
        self._refresh_quote_panel()
        self._tabs.set("📋 Cotizaciones")

    def _refresh_quote_panel(self):
        for w in self._quote_card.winfo_children():
            w.destroy()
        if not self._selected_job:
            ctk.CTkLabel(self._quote_card, text="Selecciona un trabajo",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).place(relx=0.5, rely=0.5, anchor="center")
            return
        job = self._selected_job
        breakdown = get_price_breakdown(job)
        scroll = ctk.CTkScrollableFrame(self._quote_card, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(scroll, text=f"Cotización para {job.client_name}",
                     font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))

        fields = [
            ("Tipo de trabajo:", job.job_type),
            ("Páginas:", str(job.pages)),
            ("Urgencia:", job.urgency),
            (f"Precio base ({job.pages} pág × ${config.BASE_PRICE_PER_PAGE_MXN:.0f}):", f"${breakdown['base']:,.2f}"),
            ("Multiplicador urgencia:", f"×{breakdown['urgency_multiplier']}"),
            ("Multiplicador tipo:", f"×{breakdown['type_multiplier']}"),
            ("Factor complejidad:", f"×{breakdown['complexity_factor']}"),
        ]
        for label, value in fields:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY, width=240, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=theme.FONT_BODY,
                         text_color=theme.TEXT_PRIMARY).pack(side="left")

        ctk.CTkFrame(scroll, height=2, fg_color=theme.BORDER).pack(fill="x", pady=8)

        total_row = ctk.CTkFrame(scroll, fg_color="transparent")
        total_row.pack(fill="x")
        ctk.CTkLabel(total_row, text="TOTAL:", font=("Segoe UI", 16, "bold"),
                     text_color=theme.TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(total_row, text=f"${breakdown['total']:,.2f} MXN",
                     font=("Segoe UI", 24, "bold"), text_color=theme.ACCENT_GREEN).pack(side="left", padx=16)

        ctk.CTkLabel(scroll, text=f"Anticipo sugerido (50%): ${breakdown['advance_suggested']:,.2f} MXN",
                     font=theme.FONT_BODY, text_color=theme.ACCENT_ORANGE).pack(anchor="w", pady=6)

        def apply_price():
            job.price_mxn = breakdown['total']
            self._ledger.update_job(job)
            self.toast("Precio aplicado al trabajo", "success")
            self._refresh_jobs()

        def copy_whatsapp():
            msg = generate_whatsapp_message(job, breakdown['total'])
            self.clipboard_clear()
            self.clipboard_append(msg)
            self.toast("Mensaje copiado al portapapeles", "success")

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", pady=12)
        self.primary_button(btn_row, "✓ Aplicar Precio", apply_price).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="📱 Copiar WhatsApp", width=160,
                      fg_color=theme.ACCENT_GREEN, hover_color="#16A34A",
                      font=theme.FONT_BODY, command=copy_whatsapp).pack(side="left")

    def _new_job_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Nuevo Trabajo")
        dlg.geometry("440x540")
        dlg.grab_set()

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(scroll, text="Nuevo Trabajo", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))

        fields: dict = {}
        form_fields = [
            ("Nombre del cliente", "client_name", "entry", None),
            ("Teléfono (opcional)", "client_phone", "entry", None),
            ("Tipo de trabajo", "job_type", "menu", JOB_TYPES),
            ("Páginas", "pages", "entry", None),
            ("Urgencia", "urgency", "menu", URGENCIES),
            ("Fecha de entrega (dd/mm/yyyy)", "deadline", "entry", None),
            ("Notas adicionales", "notes", "textbox", None),
        ]
        for label, key, ftype, options in form_fields:
            ctk.CTkLabel(scroll, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 2))
            if ftype == "entry":
                w = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY,
                                 text_color=theme.TEXT_PRIMARY, height=34)
                w.pack(fill="x")
                if key == "pages":
                    w.insert(0, "1")
            elif ftype == "menu":
                w = ctk.CTkOptionMenu(scroll, values=options, fg_color=theme.BG_TERTIARY,
                                      button_color=theme.ACCENT_BLUE,
                                      text_color=theme.TEXT_PRIMARY)
                w.pack(fill="x")
            elif ftype == "textbox":
                w = ctk.CTkTextbox(scroll, height=70, fg_color=theme.BG_TERTIARY,
                                   text_color=theme.TEXT_PRIMARY)
                w.pack(fill="x")
            fields[key] = (ftype, w)

        def create():
            try:
                pages = int(fields["pages"][1].get() or "1")
                if pages < 1:
                    pages = 1
            except ValueError:
                pages = 1

            def get_val(key):
                ftype, w = fields[key]
                if ftype in ("entry",):
                    return w.get().strip()
                elif ftype == "menu":
                    return w.get()
                elif ftype == "textbox":
                    return w.get("0.0", "end").strip()
                return ""

            job = ClientJob(
                client_name=get_val("client_name"),
                client_phone=get_val("client_phone"),
                job_type=get_val("job_type"),
                pages=pages,
                urgency=get_val("urgency"),
                deadline=get_val("deadline"),
                notes=get_val("notes"),
                price_mxn=calculate_price(ClientJob(pages=pages, urgency=get_val("urgency"), job_type=get_val("job_type"))),
            )
            self._ledger.add_job(job)
            dlg.destroy()
            self._refresh_jobs()
            self.toast(f"Trabajo de {job.client_name} creado", "success")

        self.primary_button(dlg, "Crear Trabajo", create).pack(pady=12)

    def _change_status_dialog(self, job: ClientJob):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Cambiar Estado")
        dlg.geometry("320x300")
        dlg.grab_set()

        ctk.CTkLabel(dlg, text=f"Estado de: {job.client_name}",
                     font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY).pack(pady=16, padx=20)

        for status in JOB_STATUSES:
            color = STATUS_COLORS.get(status, "#888")
            ctk.CTkButton(
                dlg, text=status, fg_color=color, hover_color=theme.BG_TERTIARY,
                font=theme.FONT_BODY, height=36,
                command=lambda s=status: self._set_status(job, s, dlg),
            ).pack(fill="x", padx=20, pady=3)

    def _set_status(self, job: ClientJob, status: str, dlg):
        job.status = status
        self._ledger.update_job(job)
        # Keep _selected_job in sync so the quote panel reflects the new status
        if self._selected_job and self._selected_job.id == job.id:
            self._selected_job = job
        dlg.destroy()
        self._refresh_jobs()
        self.toast(f"Estado actualizado: {status}", "success")

    def _delete_job(self, job: ClientJob):
        if messagebox.askyesno("Eliminar", f"¿Eliminar trabajo de '{job.client_name}'?"):
            self._ledger.delete_job(job.id)
            self._refresh_jobs()
            self.toast("Trabajo eliminado", "info")

    def _refresh_payments(self):
        for w in self._payments_scroll.winfo_children():
            w.destroy()
        payments = self._ledger.get_payments()
        total = self._ledger.total_income()
        self._totals_label.configure(text=f"Total ingresado: ${total:,.2f} MXN")
        if not payments:
            ctk.CTkLabel(self._payments_scroll, text="Sin pagos registrados",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=20)
            return
        for pay in reversed(payments):
            row_frame = self.card_frame(self._payments_scroll)
            row_frame.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row_frame, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(inner, text=f"📅 {pay.date}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED, width=90).pack(side="left")
            ctk.CTkLabel(inner, text=pay.client_name or "—", font=theme.FONT_BODY,
                         text_color=theme.TEXT_PRIMARY).pack(side="left", padx=8)
            ctk.CTkLabel(inner, text=pay.concept or "—", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY).pack(side="left")
            kind = "Anticipo" if pay.is_advance else "Pago"
            ctk.CTkLabel(inner, text=f"${pay.amount:,.2f} ({kind})",
                         font=("Segoe UI", 12, "bold"), text_color=theme.ACCENT_GREEN).pack(side="right")

    def _new_payment_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Registrar Pago")
        dlg.geometry("380x360")
        dlg.grab_set()

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=12)

        ctk.CTkLabel(scroll, text="Registrar Pago", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))

        jobs = self._ledger.get_jobs()
        job_options = ["(Sin trabajo)"] + [f"{j.client_name} - {j.job_type}" for j in jobs]

        ctk.CTkLabel(scroll, text="Trabajo:", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(anchor="w")
        job_menu = ctk.CTkOptionMenu(scroll, values=job_options, fg_color=theme.BG_TERTIARY,
                                     button_color=theme.ACCENT_BLUE, text_color=theme.TEXT_PRIMARY)
        job_menu.pack(fill="x")

        ctk.CTkLabel(scroll, text="Cliente:", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        client_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY)
        client_entry.pack(fill="x")

        ctk.CTkLabel(scroll, text="Concepto:", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        concept_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY)
        concept_entry.pack(fill="x")

        ctk.CTkLabel(scroll, text="Monto (MXN):", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        amount_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY)
        amount_entry.pack(fill="x")

        is_advance_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(scroll, text="¿Es anticipo?", variable=is_advance_var,
                      progress_color=theme.ACCENT_BLUE, text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=8)

        def save():
            try:
                amount = round(float(amount_entry.get().replace(",", "").strip() or "0"), 2)
            except ValueError:
                amount = 0.0
            if amount <= 0:
                messagebox.showerror("Monto inválido", "El monto debe ser mayor a $0.00 MXN.", parent=dlg)
                return
            job_idx = job_options.index(job_menu.get()) - 1
            job_id = jobs[job_idx].id if 0 <= job_idx < len(jobs) else ""
            pay = Payment(
                job_id=job_id,
                client_name=client_entry.get().strip(),
                concept=concept_entry.get().strip(),
                amount=amount,
                is_advance=is_advance_var.get(),
            )
            self._ledger.add_payment(pay)
            dlg.destroy()
            self._refresh_payments()
            self.toast(f"Pago de ${amount:,.2f} registrado", "success")

        self.primary_button(dlg, "Guardar Pago", save).pack(pady=10)

    def _refresh_dashboard(self):
        total = self._ledger.total_income()
        active = self._ledger.active_jobs_count()
        jobs = self._ledger.get_jobs()
        pending = round(sum(j.price_mxn for j in jobs if j.status not in ("Pagado", "Cancelado")), 2)

        if len(self._dash_cards) >= 3:
            # Animate counting up each stat — guard each widget still exists
            if self._dash_cards[0].winfo_exists():
                count_up(self._dash_cards[0], total, prefix="$", suffix=" MXN",
                         steps=22, step_ms=25, is_float=True)
            if self._dash_cards[1].winfo_exists():
                count_up(self._dash_cards[1], active,
                         steps=18, step_ms=30, is_float=False)
            if self._dash_cards[2].winfo_exists():
                count_up(self._dash_cards[2], pending, prefix="$", suffix=" MXN",
                         steps=22, step_ms=25, is_float=True)

        self._draw_status_chart(jobs)

    def _draw_status_chart(self, jobs: list[ClientJob]):
        # Cancel any in-flight pie animation before starting a new one
        if self._pie_anim_job is not None:
            try:
                self.after_cancel(self._pie_anim_job)
            except Exception:
                pass
            self._pie_anim_job = None

        self._chart_canvas.delete("all")
        if not jobs:
            self._chart_canvas.create_text(250, 100, text="Sin datos", fill=theme.TEXT_MUTED)
            return

        from collections import Counter
        counts = Counter(j.status for j in jobs)
        total_count = sum(counts.values())
        if total_count == 0:
            self._chart_canvas.create_text(250, 100, text="Sin datos", fill=theme.TEXT_MUTED)
            return
        cx, cy, r = 100, 100, 80
        legend_x = 210

        # Build arc specs
        arcs = []
        start_angle = 90  # start from top
        for status, count in counts.items():
            extent = 360 * count / total_count
            color = STATUS_COLORS.get(status, "#888")
            arcs.append((status, count, start_angle, extent, color))
            start_angle += extent

        # Draw legend immediately
        for i, (status, count, _sa, _ext, color) in enumerate(arcs):
            ly = 20 + i * 24
            self._chart_canvas.create_rectangle(
                legend_x, ly, legend_x + 14, ly + 14, fill=color, outline="")
            self._chart_canvas.create_text(
                legend_x + 20, ly + 7,
                text=f"{status}: {count}",
                anchor="w", fill=theme.TEXT_PRIMARY, font=("Segoe UI", 10),
            )

        # Animate arcs drawing one at a time
        self._animate_pie_arcs(arcs, cx, cy, r, 0, 0.0)

    def _animate_pie_arcs(self, arcs, cx, cy, r, arc_idx, progress):
        if not self.winfo_exists():
            return
        if arc_idx >= len(arcs):
            self._pie_anim_job = None
            return
        status, count, start_angle, extent, color = arcs[arc_idx]
        steps = max(6, int(extent / 8))
        step_ms = 12

        drawn_extent = extent * progress

        self._chart_canvas.delete(f"arc_{arc_idx}")
        if drawn_extent > 0.5:
            self._chart_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle, extent=drawn_extent,
                fill=color, outline=theme.BG_SECONDARY, width=2,
                tags=f"arc_{arc_idx}",
            )

        new_progress = progress + 1.0 / steps
        if new_progress < 1.0:
            self._pie_anim_job = self.after(
                step_ms,
                lambda: self._animate_pie_arcs(arcs, cx, cy, r, arc_idx, new_progress)
            )
        else:
            # Draw final arc fully, move to next
            self._chart_canvas.delete(f"arc_{arc_idx}")
            self._chart_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle, extent=extent,
                fill=color, outline=theme.BG_SECONDARY, width=2,
                tags=f"arc_{arc_idx}",
            )
            self._pie_anim_job = self.after(
                step_ms,
                lambda: self._animate_pie_arcs(arcs, cx, cy, r, arc_idx + 1, 0.0)
            )

    def on_hide(self):
        if self._pie_anim_job is not None:
            try:
                self.after_cancel(self._pie_anim_job)
            except Exception:
                pass
            self._pie_anim_job = None

    def on_show(self):
        self._refresh_jobs()
        self._refresh_payments()
        self._refresh_dashboard()
