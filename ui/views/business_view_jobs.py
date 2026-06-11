"""BusinessJobsMixin — gestión de trabajos (jobs) + panel de cotización.

Separado de business_view.py. Depende de:
  • self._ledger, self._selected_job
  • self._jobs_scroll, self._quote_card, self._tabs
  • self.primary_button, self.toast, self.clipboard_*
"""
from tkinter import messagebox

import customtkinter as ctk

import config
from core.businesscore.estimator import (
    calculate_price,
    generate_whatsapp_message,
    get_price_breakdown,
)
from core.businesscore.models import (
    JOB_STATUSES,
    JOB_TYPES,
    URGENCIES,
    ClientJob,
)
from ui import theme
from ui.modal_utils import safe_grab


class BusinessJobsMixin:
    """Lista de trabajos, dialogs de creación/edición y panel de cotización."""

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

        status_color = theme.STATUS_COLORS.get(job.status, "#888")
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

        def open_whatsapp():
            import webbrowser
            from urllib.parse import quote
            msg = generate_whatsapp_message(job, breakdown['total'])
            phone = (job.client_phone or "").lstrip("+").replace(" ", "").replace("-", "")
            url = (f"https://wa.me/{phone}?text={quote(msg)}"
                   if phone else f"https://wa.me/?text={quote(msg)}")
            webbrowser.open(url)

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", pady=12)
        self.primary_button(btn_row, "✓ Aplicar Precio", apply_price).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="📋 Copiar WhatsApp", width=160,
                      fg_color=theme.ACCENT_GREEN, hover_color="#16A34A",
                      font=theme.FONT_BODY, command=copy_whatsapp).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="📱 Abrir WhatsApp", width=160,
                      fg_color="#25D366", hover_color="#128C7E",
                      font=theme.FONT_BODY, command=open_whatsapp).pack(side="left")

    def _new_job_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Nuevo Trabajo")
        dlg.geometry("440x540")
        safe_grab(dlg, self)

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
                if ftype == "entry":
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
        safe_grab(dlg, self)

        ctk.CTkLabel(dlg, text=f"Estado de: {job.client_name}",
                     font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY).pack(pady=16, padx=20)

        for status in JOB_STATUSES:
            color = theme.STATUS_COLORS.get(status, "#888")
            ctk.CTkButton(
                dlg, text=status, fg_color=color, hover_color=theme.BG_TERTIARY,
                font=theme.FONT_BODY, height=36,
                command=lambda s=status: self._set_status(job, s, dlg),
            ).pack(fill="x", padx=20, pady=3)

    def _set_status(self, job: ClientJob, status: str, dlg):
        job.status = status
        self._ledger.update_job(job)
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
