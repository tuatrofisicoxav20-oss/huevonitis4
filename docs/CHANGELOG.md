# Changelog — Huevonitis 4

## [4.1.0] — 2026-05-22 (integración end-to-end + limpieza)

### Bugs de integración corregidos
- **A1**: UI "Pipeline avanzada" ahora propaga `use_pipeline`, `pipeline_config`
  y `min_quality` al `GlyphExtractor.extract_from_image()`.
- **A2/A3**: `bank.add_glyph()` acepta `predicted_char`, `label_confidence`,
  `detector_sources` y `quality_override`; `save_glyphs_to_bank` los pasa,
  eliminando el doble cómputo de quality.
- **A4**: "Reescribir con mi letra" transfiere el texto real a InkCore Escritor
  vía `app_state.study_text`; `on_show()` lo carga automáticamente.
- **A5**: `FallbackGlyphClassifier` eliminado de InkCoreView (dead code).
- **A6**: `extractor_preprocess.py` y `extractor_segments.py` marcados como
  DEPRECATED con `DeprecationWarning`.
- **Hotfix OCR cache**: `invalidate()` ahora filtra por source_path en vez
  de borrar todo el caché.
- **Hotfix double toast**: eliminado toast redundante "Texto importado" en
  `_on_ocr_done`.

### Estructura del Document aprovechada
- **B1**: `renderer.render_document(doc, options)` — renderiza con jerarquía
  (headings escalados, bullets para list_item, páginas A4).
- **B2**: `export_document_pdf(doc, path)` — PDF con estilos por block_type
  (Heading→H1/H2/H3, list_item→bullet, code→Courier).
- **B3**: `export_rendered_pages_pdf(images, path)` — pega imágenes renderizadas
  como páginas A4 de un PDF.
- **B4**: Botón "📄 Exportar PDF con mi letra" en InkCore Escritor.
- **B5**: `build_study_bundle_from_document(doc)` — flashcards de alta
  confianza desde headings, key_terms ordenados, quiz solo desde párrafos.
- **B6**: Cache de StudyBundle migrado de in-memory a `shelve` con TTL 30 días.

### Calidad de vida
- **C1**: Sección "Diagnóstico" en Settings → ventana con `get_report()`,
  copiar al portapapeles y limpiar eventos.
- **C2**: Botón "📱 Abrir WhatsApp" en cotizaciones → abre `wa.me/` con
  número y mensaje pre-rellenado.
- **C3**: `psutil` documentado en `requirements-optional.txt`.

### Tests nuevos (D1–D5)
- `test_bank_ensemble_metadata.py` (3 tests)
- `test_studycore_document.py` (4 tests)
- `test_pipeline_options_wiring.py` (2 tests)
- `test_pdf_exporter.py` (3 tests)
- Total: 100 tests pasando (96 anteriores + 12 nuevos - 8 ya existentes).

---

## [4.0.1] — 2026-05-21 (sesión de limpieza técnica)

### Infra / higiene (F1)
- Añadido `.gitignore`, `pyproject.toml` (ruff + pytest), `docs/`
- `requirements.txt`: `>=` → `~=` en todas las dependencias
- `tools/compare_strategies.py`: eliminado `default_image` hardcodeado → argparse obligatorio
- `core/inkcore/ai/classifier.py`: notas de integración IA movidas a `docs/ai-integration-notes.md`
- ruff `--fix`: 113+ issues auto-corregidos (imports, UP, I)

### Modelos (F2)
- `core/models.py` como SSOT: añadido `Project.status = "Borrador"` (#5)
- `core/businesscore/models.py`: re-exporta desde `core.models`; `JOB_STATUSES/JOB_TYPES/URGENCIES` generados desde Enums (#1)
- `core/studycore/models.py`: re-exporta desde `core.models` (#1)
- `STATUS_COLORS` unificado en `ui/theme.py`; eliminado de `businesscore/models.py` (#7)

### Bugs de lógica (F3)
- `extractor.py`: `import re` movido a nivel de módulo (#17)
- `reporter.py`: `status_lbl` definido antes del botón que lo referencia (#16)
- `pdf_exporter.py`: `tempfile.NamedTemporaryFile` + márgenes 2 cm (#14)
- `bank.py`: cálculo de hashes dentro del lock — elimina race condition (#15)
- `settings_view.py`: opción "Claro" removida; `_save_settings` atómico; validación de números (#6)
- `config.py`: `load_settings()` aplica `settings.json` a módulo al inicio (#6)
- `inkcore_view._export_png` → worker thread (#8)
- `study_view._import_word` → worker thread (#8)
- `builder.py`: `build_study_bundle` cacheado con SHA-256 (#9)
- `canvas_editor.py`: `_push_undo` en drag-start y edit-text; stack máx 50 (#10)
- `canvas_editor.py`: image cache `(path,w,h)→PhotoImage` FIFO máx 50 (#11)
- `projects_view._load_project`: `askyesnocancel` ante cambios sin guardar (#12)
- `serializer.py`: `project_to_dict/project_from_dict` incluye campo `status`

### Extractor (F4)
- `extractor_segments.py`: doble import PIL eliminado; stubs `pass` removidos; `_BBoxRef` eliminado
- `extractor.py`: `_BBox` renombrado a `BBox` (API pública); alias `_BBox = BBox` para compat; imports de módulos auxiliares activados

### Limpieza (F5)
- Eliminados `inkcore_{extractor,bank,writer,review}_tab.py` (placeholders sin uso)
- Eliminados `controllers/` y `services/` (carpetas vacías)

### Polish (F6)
- `ui/theme.py`: `init_fonts()` elige entre Segoe UI/Inter/DejaVu Sans/Liberation Sans/Helvetica/TkDefaultFont según disponibilidad (#18)
- `reporter.py`: fallback theme usa `TkDefaultFont`; inline fonts usan `theme.FONT_*`
- `ledger.py`, `project_manager.py`: `except Exception` → tipos específicos en paths críticos (#20)

### Tests (F7)
- `tests/` con 63 tests pytest: serializer, estimator, bank, ledger, studycore, pipeline
- `conftest.py`: fixture `patch_config_dirs` redirige `DATA_DIR` a `tmp_path`
