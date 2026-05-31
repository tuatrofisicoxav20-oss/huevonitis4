"""StudyBundleMixin — generación del bundle de estudio, resumen y exportación.

Separado de study_view.py. Depende de:
  • self._bundle (StudyBundle), self._last_document
  • self.toast() (BaseView)
  • Widgets: self._text_input, self._summary_box
"""
from tkinter import filedialog

from core.export.pdf_exporter import export_text_pdf
from core.studycore.builder import build_study_bundle, build_study_bundle_from_document


class StudyBundleMixin:
    """Texto fuente, construcción del bundle, resumen y exportaciones."""

    def _get_text(self) -> str:
        return self._text_input.get("0.0", "end").strip()

    def _ensure_bundle(self):
        text = self._get_text()
        if not text:
            self.toast("Ingresa o importa texto primero", "warning")
            return False
        if self._last_document is not None and self._last_document.pages:
            self._bundle = build_study_bundle_from_document(self._last_document)
        else:
            self._bundle = build_study_bundle(text)
        return True

    def _gen_summary(self):
        if not self._ensure_bundle():
            return
        self._summary_box.configure(state="normal")
        self._summary_box.delete("0.0", "end")
        self._summary_box.insert("0.0", self._bundle.summary or "(Sin resumen generado)")
        self._summary_box.configure(state="disabled")
        self.toast("Resumen generado", "success")

    def _export_summary_pdf(self):
        if not self._bundle:
            self.toast("Genera el resumen primero", "warning")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")])
        if path:
            ok = export_text_pdf(self._bundle.summary, path, title="Resumen")
            self.toast("PDF exportado" if ok else "Error al exportar", "success" if ok else "error")

    def _export_markdown(self):
        """Exporta el documento importado o el texto actual como Markdown."""
        if self._last_document is not None:
            md_content = self._last_document.to_markdown()
        else:
            text = self._get_text()
            if not text:
                self.toast("No hay texto para exportar", "warning")
                return
            md_content = text

        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Texto", "*.txt")],
            title="Exportar como Markdown",
        )
        if not path:
            return
        try:
            import os
            fd, tmp = __import__("tempfile").mkstemp(
                dir=os.path.dirname(path), suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(md_content)
            os.replace(tmp, path)
            self.toast("Markdown exportado", "success")
        except Exception as exc:
            self.toast(f"Error al exportar: {exc}", "error")
