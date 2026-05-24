# Arquitectura — Huevonitis 4

Vista general de la app y cómo los módulos se conectan.

## Capas

```
┌─────────────────────────────────────────────────────┐
│                       ui/                           │
│      vistas, componentes, theme (NUNCA core lógico) │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                      core/                          │
│  modelos, lógica de negocio, pipeline, OCR, render  │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                    config.py                        │
│      constantes globales, settings.json loader      │
└─────────────────────────────────────────────────────┘
```

**Regla:** `core/*` NO importa `tkinter`, `customtkinter`, ni nada de `ui/*`.
`ui/*` SÍ importa `core/*`. Si esto se viola, es un bug.

## Módulos principales

### `core/`

| Módulo | Responsabilidad |
|---|---|
| `models.py` | SSOT de dataclasses — Project, Page, ClientJob, GlyphEntry, Flashcard, etc. |
| `serializer.py` | JSON ↔ dataclasses (project_to_dict / project_from_dict). |
| `project_manager.py` | CRUD de proyectos con escritura atómica + `.bak` + autosave. Borrado seguro restringido a `DATA_DIR`. |
| `diagnostics.py` | Colector de eventos, tiempos y errores recientes. |

### `core/inkcore/`

| Módulo | Responsabilidad |
|---|---|
| `bank.py` | `GlyphBank` — banco persistente, dedup por hash, borrado restringido a `bank_dir`. |
| `extractor.py` | Pipeline clásico de extracción (segmentación CV + alineación con texto de referencia). |
| `extraction_pipeline.py` | Pipeline ensemble nuevo (detectores + fusión + labelers + voting). |
| `bulk_capture.py` | Captura masiva — `run()` para imágenes, `run_pdf()` por lotes de 2 páginas. |
| `renderer.py` | `HandwritingRenderer` — pega glifos sobre página A4. |
| `reporter.py` | `InkCoreReporter` — PDF del banco con muestras y métricas. |
| `pipeline.py` | `InkCorePipeline` — orquesta extractor + banco + renderer. |
| `quality.py` | `assess_glyph()` — score 0-1, tier Bronze/Silver/Gold. |
| `glyph_detectors/` | Detectores intercambiables: `classic_cv`, `craft` (opcional). |
| `glyph_labelers/` | Labelers: `trocr_labeler` (opcional). Voting: `highest_conf`, `majority`, `consensus`. |
| `model_cache.py` | Caché de modelos ML en RAM con limpieza explícita. |

### `core/ocr/`

| Módulo | Responsabilidad |
|---|---|
| `ingestion.py` | `DocumentIngestion` — router por extensión (PDF / DOCX / imagen / carpeta). |
| `engine.py` | `OCREngine` — interfaz uniforme sobre backends. |
| `backends/` | Backends intercambiables: tesseract, paddleocr, easyocr, doctr. |
| `document_readers/` | Lectores nativos: `pdf_reader`, `docx_reader`, `pdf_classifier`. |
| `document_model.py` | `Document`, `DocumentPage`, `TextBlock` — modelo estructurado. |
| `result_cache.py` | Caché en disco de resultados OCR, clave `sha256(path+mtime+size+backend+opts)`. |

### `core/studycore/`

| Módulo | Responsabilidad |
|---|---|
| `builder.py` | `build_study_bundle(text)` y `build_study_bundle_from_document(doc)`. Caché shelve. |
| `models.py` | Re-exports de Flashcard, QuizQuestion, StudyBundle. |

### `core/businesscore/`

| Módulo | Responsabilidad |
|---|---|
| `estimator.py` | Cálculo de precio MXN (precio_base × páginas × urgencia × tipo). |
| `ledger.py` | CRUD de ClientJob + Payment con persistencia JSON atómica. |

### `core/export/`

| Módulo | Responsabilidad |
|---|---|
| `pdf_exporter.py` | `export_document_pdf`, `export_rendered_pages_pdf`. |

### `ui/`

| Carpeta | Responsabilidad |
|---|---|
| `app.py` | `HuevonitisApp` — Tk root, sidebar, gestión de vistas, spinner global. |
| `theme.py` | Paletas dark/light, fuentes, navegación. `apply_theme(mode)`. |
| `animations.py` | `count_up()` y helpers. |
| `components/` | Reusables: `CanvasEditor`, `Card`, `Sidebar`, `Toast`. |
| `views/` | Una por sección de la app (Dashboard, Proyectos, Estudio, InkCore, Negocio, Config). |
| `views/inkcore/` | Mixins por tab: `extractor_tab`, `bulk_capture_tab`, `bank_tab`, `writer_tab`, `review_tab`, `pipeline_panel`. |

## Flujos clave

### Extracción de un glifo (legacy)

```
Imagen + texto_ref
  → ImagePreprocessor (deskew, denoise, threshold)
  → SegmentDetector (líneas, palabras, caracteres)
  → AlignmentEngine (DP entre boundaries y texto_ref)
  → quality.assess_glyph (score por glifo)
  → filtro min_quality
  → GlyphBank.add_glyph (copia a bank_dir, dedup)
```

### Extracción ensemble

```
Imagen
  → cada GlyphDetector activo (boxes con score)
  → detector_fusion (union / intersection / cascade)
  → cada GlyphLabeler activo (char + confidence por crop)
  → labeler_voting (highest_conf / majority / consensus)
  → quality.assess_glyph
  → filtro min_quality + min_label_confidence
  → ExtractionResult (lista de GlyphEntry)
```

### Captura masiva de PDF

```
PDF
  → pdfinfo_from_path (total_pages)
  → loop por lotes de 2 páginas:
    → convert_from_path(first_page, last_page, dpi=300)
    → _save_temp(pil_img) → PNG temporal en DATA_DIR/temp_bulk_capture/
    → _extract_from_image (pipeline ensemble)
    → unlink(temp) → liberar RAM
    → append BulkGlyphCandidate con source_label="Página N"
  → TrOCR post-labeling (si pipeline no lo hizo)
  → BulkCaptureSession con stats + elapsed_s
  → UI muestra grid de candidatos para aprobar/rechazar
  → commit aprobados → GlyphBank.add_glyph(...)
```

### OCR de documento

```
source_path (PDF/DOCX/imagen/carpeta)
  → DocumentIngestion.ingest(path)
  → cache.get(path, backend, opts) → si hit, devuelve Document
  → router por extensión:
    .pdf  → classify_pdf (texto/escaneado/mixto) → pdfplumber / OCR
    .docx → docx_reader
    .doc  → mensaje "no compatible" (no más excepciones crípticas)
    image → backend OCR activo (tesseract/easyocr/...)
    folder → cada imagen como página
  → cache.put(path, document, backend, opts)
  → StudyView puede convertir Document → StudyBundle
```

## Persistencia

Todo bajo `~/.local/share/huevonitis4/`:

```
projects/         proyectos JSON (uno por archivo) + .bak
tipografia/       GlyphBank — bank.json + bank_dir/*.png
business/         ledger.json (ClientJob + Payment)
autosave/         {project_id}_autosave.json (cada 30s mientras la app corre)
exports/          PDFs/PNGs generados
ocr_cache/        *.pkl con resultados OCR
models/           descargas de modelos ML (TrOCR, etc.)
debug_extractions/ overlays de depuración del extractor
temp_bulk_capture/ páginas temp del run_pdf (limpiables con tools/clean.py)
study_bundle_cache/ shelve con bundles cacheados
settings.json     ajustes de usuario
app.log           log rotativo
```

## Reglas de seguridad

1. **Borrado restringido**: `GlyphBank.remove_glyph` y `ProjectManager.delete`
   solo eliminan archivos cuya ruta cae dentro del directorio gestionado
   (`bank_dir` / `DATA_DIR`). Rutas externas se loggean y se omiten.
2. **Escritura atómica**: `ledger.py`, `project_manager.py`, `bank.py` escriben
   primero a `.tmp` y luego `os.replace()`. Si falla mid-write, el archivo
   anterior queda intacto.
3. **Backup `.bak`**: antes de cada `save()` se copia el archivo previo a
   `.bak`. `load()` cae a `.bak` si el principal está corrupto.
4. **No tocar archivos externos**: ningún código en `core/` debe escribir o
   borrar fuera de `DATA_DIR` salvo cuando el usuario lo solicite explícitamente
   (export, save-as, etc.).

## Tests

- 127 tests (1 skipped — e2e requiere fixtures reales).
- `pytest -q` desde la raíz.
- `pytest -m slow` para los marcados lentos.
- Coverage: lógica core, serialización, banco, ledger, studycore, pipeline,
  exporter, ingestion, safety guards.
- No hay tests de UI (mixins de tkinter requieren Xvfb).

## Herramientas internas

| Script | Uso |
|---|---|
| `tools/doctor.py` | Diagnóstico de entorno (deps, dirs, settings). |
| `tools/clean.py` | Limpieza de temporales con `--dry-run`. |
| `tools/measure_fixture.py` | Genera `expectations.json` desde una imagen real. |
| `tools/compare_strategies.py` | Compara estrategias de segmentación CLI. |
