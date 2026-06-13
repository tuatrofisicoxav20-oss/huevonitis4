# Fixtures de plantilla (PDFs reales)

`lote_20260611.pdf` — 29 páginas de fotos de celular de plantillas rellenas
(convertidas a PDF con una app, ~300dpi equivalente). Es el lote real del
usuario usado como baseline del fix de extracción (fases E0–E5).

No va a git por peso (5.9 MB). Para reproducir: pedirle el PDF al usuario
(`Image to PDF 20260611 22.56.29.pdf` en sus Descargas) y copiarlo acá con
este nombre. El harness es `tools/diag_template_pdf.py`; los CSV de
baseline/post viven en `reports/extraccion_fix/`.
