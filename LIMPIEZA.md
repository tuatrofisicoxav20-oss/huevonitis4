# LIMPIEZA — eliminación de código muerto y remodelación de UI

Objetivo: borrar el extractor viejo "normal", la pestaña "Reproducir", los
detectores neuronales y backends OCR desconectados; dejar UN flujo claro de
captura de glifos (Plantilla → Captura → Revisión → Banco → Escritor).

## FASE 0 — Baseline (pre-limpieza)

Tag de respaldo: **`pre-limpieza`** (sobre `356865e`). Rollback: `git reset --hard pre-limpieza`.

### Tests (baseline)
- **322 passed, 3 skipped**, 0 failed — `python -m pytest -q` en ~59s.

### Arranque
- Import de `ui.views.inkcore.main_view`: **0.34s** (TrOCR/transformers se cargan
  de forma perezosa, no al importar — la carga pesada de ~10s ocurre la primera
  vez que se usa el extractor viejo, no al arrancar).

### Tamaño (baseline)
- Archivos `.py` (sin `.git`): **229**
- Líneas de código totales: **34 830**

---

## Progreso por fase

- **Fase 1** ✅ — borrados detectores neuronales (craft/paddle/easyocr) y backends
  OCR (doctr/paddleocr/easyocr). Suite 319.
- **Fase 2** ✅ — eliminado "Reproducir"/replicator (3 archivos + test). Suite 315.
- **Fase 3** ✅ — desacople: nuevo `glyph_ingest.py` (motor de imagen limpio);
  Captura/Plantilla ya no dependen de la fachada `GlyphExtractor`; quitado el
  preload de TrOCR. Suite 315.
- **Fase 4** ✅ — borrado el extractor viejo: 13 módulos core + 6 UI + 8 tests +
  5 tools. Suite 279, 0 fallos. App sin pestaña Extractor; TrOCR no se carga al
  arrancar; Captura smoke 6/6.

### Decisiones clave (la auditoría estaba parcialmente equivocada)
El motor de imagen del "extractor viejo" está VIVO: lo usan la Captura masiva
(`extraction_pipeline`) y la Plantilla (`template_extract`). Por eso se
**conservaron** estos módulos (la auditoría los marcaba para borrar):
`extractor_preprocess`, `extractor_glyph_ops`, `extractor_align_basic`,
`wf_calibration`. También se conservó `tesseract_labeler` (cableado en el
registry/config del pipeline vivo). El resto del extractor sí se eliminó.

## Antes / Después

| Métrica            | Antes  | Tras Fase 4 | Meta     |
|--------------------|--------|-------------|----------|
| Archivos .py       | 229    | 187         | —        |
| LOC totales        | 34 830 | 27 625      | −6 800+  |
| Tests passed       | 322    | 279         | 100% ok  |
| Arranque (import)  | 0.34s  | 0.23s       | + sin preload TrOCR |

LOC eliminadas hasta Fase 4: **−7 205** (meta ~6 800 superada). Archivos: **−42**.
