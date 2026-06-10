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

- **Fase 5** ✅ — reorganización de UI: pestañas en orden de flujo con pasos
  numerados (1·Plantilla → 2·Captura → 3·Revisión → Banco → Escritor); texto de
  ayuda de Captura aclara que acepta fotos sueltas. Sin features nuevas.
- **Fase 6** ✅ — limpieza final: ruff limpio (unused imports/vars), atributos
  huérfanos del extractor fuera de `main_view`, README actualizado al flujo
  nuevo, borrados `FLUJO_EXTRACTOR.md` y refs a tools eliminados.

## Antes / Después (medido con git contra el tag `pre-limpieza`, solo `.py` trackeados)

| Métrica            | Antes (pre-limpieza) | Después | Δ        |
|--------------------|----------------------|---------|----------|
| Archivos .py       | 229                  | 191     | **−38**  |
| Líneas .py         | 34 818               | 28 371  | **−6 447** neto |
| Tests              | 322 passed / 3 skip  | 279 passed / 0 skip | −43 (todos de código muerto) |
| Arranque           | preload TrOCR ~10s en background al iniciar | sin preload (TrOCR no se carga) | — |

`git diff pre-limpieza HEAD -- '*.py'`: **7 735 líneas borradas**, 1 205 añadidas
(el neto −6 447 incluye `glyph_ingest.py` + comentarios nuevos). Borrado bruto
supera la meta de ~6 800.

## Grep de verificación (GATE 6) — cero referencias vivas
`replicator`/`Reproducir` = 0 · `auto_text` import = 0 (solo 1 comentario
histórico) · detectores/backends neuronales como módulo = 0 · `GlyphExtractor` /
`from core.inkcore.extractor import` = 0.

## Lo que se CONSERVÓ a propósito (la auditoría se equivocaba)
El motor de imagen del extractor viejo está VIVO (lo usan Captura + Plantilla):
`extractor_preprocess`, `extractor_glyph_ops`, `extractor_align_basic`,
`wf_calibration`, más `tesseract_labeler` (cableado en el pipeline). `BBox` se
movió a `glyph_detectors/base.py`. Todo lo demás del extractor se eliminó.
