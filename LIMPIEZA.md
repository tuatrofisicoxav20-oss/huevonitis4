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

## Antes / Después (se completa en Fase 6)

| Métrica            | Antes  | Después |
|--------------------|--------|---------|
| Archivos .py       | 229    | —       |
| LOC totales        | 34 830 | —       |
| Tests passed       | 322    | —       |
| Arranque (import)  | 0.34s  | —       |
