"""InkCore reporter — facade que delega a reporter_pdf + reporter_modal."""
import logging

logger = logging.getLogger(__name__)


class InkCoreReporter:
    """Genera reportes del banco. PDF y modal viven en módulos separados."""

    def generate_report(self, bank) -> dict:
        """Genera los datos del informe a partir del GlyphBank."""
        return bank.get_bank_report()

    def export_pdf(self, report_data: dict, output_path: str) -> bool:
        """Exporta el informe a PDF (ver reporter_pdf.export_pdf)."""
        from core.inkcore.reporter_pdf import export_pdf
        return export_pdf(report_data, output_path)

    def show_modal(self, parent_widget, report_data: dict):
        """Muestra el informe en una ventana modal (ver reporter_modal.show_modal)."""
        from core.inkcore.reporter_modal import show_modal
        show_modal(self, parent_widget, report_data)
