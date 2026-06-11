"""BusinessPaymentsMixin — registro y dialog de pagos."""
from tkinter import messagebox

import customtkinter as ctk

from core.businesscore.models import Payment
from ui import theme
from ui.modal_utils import safe_grab


class BusinessPaymentsMixin:
    """Listado de pagos + dialog para registrar nuevo."""

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
                         font=theme.get_font("bold", 12),
                         text_color=theme.ACCENT_GREEN).pack(side="right")

    def _new_payment_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Registrar Pago")
        dlg.geometry("380x360")
        safe_grab(dlg, self)

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=12)

        ctk.CTkLabel(scroll, text="Registrar Pago", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))

        jobs = self._ledger.get_jobs()
        job_options = ["(Sin trabajo)"] + [f"{j.client_name} - {j.job_type}" for j in jobs]

        ctk.CTkLabel(scroll, text="Trabajo:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w")
        job_menu = ctk.CTkOptionMenu(scroll, values=job_options, fg_color=theme.BG_TERTIARY,
                                     button_color=theme.ACCENT_BLUE, text_color=theme.TEXT_PRIMARY)
        job_menu.pack(fill="x")

        ctk.CTkLabel(scroll, text="Cliente:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        client_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY,
                                    text_color=theme.TEXT_PRIMARY)
        client_entry.pack(fill="x")

        ctk.CTkLabel(scroll, text="Concepto:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        concept_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY,
                                     text_color=theme.TEXT_PRIMARY)
        concept_entry.pack(fill="x")

        ctk.CTkLabel(scroll, text="Monto (MXN):", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w", pady=(6, 0))
        amount_entry = ctk.CTkEntry(scroll, fg_color=theme.BG_TERTIARY,
                                    text_color=theme.TEXT_PRIMARY)
        amount_entry.pack(fill="x")

        is_advance_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(scroll, text="¿Es anticipo?", variable=is_advance_var,
                      progress_color=theme.ACCENT_BLUE,
                      text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=8)

        def save():
            try:
                amount = round(float(amount_entry.get().replace(",", "").strip() or "0"), 2)
            except ValueError:
                amount = 0.0
            if amount <= 0:
                messagebox.showerror("Monto inválido",
                                     "El monto debe ser mayor a $0.00 MXN.", parent=dlg)
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
