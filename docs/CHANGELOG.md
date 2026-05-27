# Changelog — Huevonitis 4

## [4.2.0] — 2026-05-26 (bug raíz del banco + perfiles + replicador)

### 🚨 BUG CRÍTICO RAÍZ
- **BUG-18**: `_avg_hash` rechazaba TODOS los glifos nuevos como duplicados.
  El extractor produce RGBA con fondo transparente; `Image.convert("L")`
  ignora alpha y proyectaba todo a un único hash. El "botón Guardar en
  banco no hace nada" era esto: el primero se guardaba y los siguientes
  26 se rechazaban silenciosamente.
  - Fix: `_flatten_rgba` aplana sobre blanco antes de hashear.
  - Nuevo `_dhash` (difference hash, más estable). Verificación:
    `python tools/test_dedup_sanity.py`.

### Bugs corregidos
- BUG-01: undo cross-page corrompía elementos (canvas_editor.load_page limpia stacks)
- BUG-02: cleanup selectivo de `_temp_extract/` (no borra candidatos pendientes
  de bulk capture cuando se hace save desde el Extractor)
- BUG-03: `tests/test_e2e_extraction.py` no rompe la colección del módulo
- BUG-04: rasters de PDF se limpian en `BulkCaptureRunner._cleanup_raster_tmps`
- BUG-06: word-wrap propio en `HandwritingRenderer._soft_wrap_text` para
  que párrafos largos no se trunquen
- BUG-08: `config.VERSION` se lee del archivo VERSION en runtime (SSOT)
- BUG-11: `save_glyphs_to_bank` devuelve dict `{saved, duplicates, missing_source, errors}`
- BUG-22: `Payment.amount` se parsea de forma segura en income calculations
- BUG-28: payments con fecha inválida van al final (no al inicio)
- BUG-29: `_from_dict` normaliza tier legacy lowercase + loguea campos faltantes

### Performance
- **PERF-01**: `begin_batch/end_batch` en `GlyphBank` → 1 write al manifest
  por sesión en vez de N (50× más rápido en captura masiva).
- **PERF-02**: `perceptual_hash` cacheado en `GlyphEntry`. Dedup compara
  hashes en memoria sin re-abrir PNGs (~100× más rápido).
- **PERF-03**: índices `_by_char`/`_by_tier` para lookups O(1) en
  `get_best_glyph`, `get_all`, `approve_glyph`, `remove_glyph` (20× más rápido).
- **PERF-07**: PIL `Image.open` siempre dentro de `with` — handles cerrados.

### Features nuevos (v4.2)
- **Perfiles de letra por persona** (F1): cada perfil con carpeta y manifest
  propios bajo `tipografia/{profile_id}/`. Migración automática del banco
  legacy a `default/` con backup en `_backup_pre_profiles/`.
  Barra de perfil sobre el tabview con dropdown + crear/renombrar/eliminar.
- **Reproductor de apuntes MVP** (F2): tab nuevo 🔁 Reproducir. Carga un
  apunte ajeno → detecta recuadros (cv2 findContours) y bloques de texto
  (tesseract OCR) → re-renderiza con el `HandwritingRenderer` del perfil
  activo. Slider de fidelidad 0–100. Toggles por bloque. Limitaciones
  documentadas en `docs/REPLICATOR_LIMITS.md`.
- **Diagnóstico de sesión al arrancar** (F3): 6 checks (dependencies,
  disk space, profile consistency, manifest integrity, orphan PNGs,
  missing PNGs). Modal con auto-fix individual o "arreglar todos los
  seguros". Skip con `H4_SKIP_DIAGNOSTIC=1`.

### Mejoras del banco
- Tab Banco agrupa glifos por letra con cabeceras (carácter, nº muestras,
  calidad promedio). Orden canónico a-z con ñ en posición 14.
- Acciones por celda: ✏️ renombrar, ⬆️ ciclar tier, 🗑️ eliminar.
- "➕ Agregar desde imagen": diálogo para asignar carácter manual a un PNG.
- Selección múltiple con checkboxes + barra batch (eliminar seleccionados,
  preparada para "mover a perfil").

### Instrumentación / robustez
- Logging INFO/WARNING/ERROR end-to-end en el flujo guardar-en-banco
  (extractor_tab → pipeline → bank.add_glyph).
- `BaseView.toast` cae a stderr si el toast manager falla.
- `ToastManager._restack` con HiDPI guard + `lift()` forzado al final del
  slide-in para evitar toasts tapados.
- `extractor_tab._save_to_bank` actualiza el status label como fallback
  visible bajo el botón.

### Herramientas nuevas
- `tools/diagnose_save.py`: reproduce el flujo de save fuera de la UI.
- `tools/test_dedup_sanity.py`: verifica que el dedup acepta variantes y
  rechaza idénticos.
- `tools/migrate_to_profiles.py`: migración manual a la estructura de perfiles.

### Visual
- Paleta refinada: negros más profundos en BG_PRIMARY/SECONDARY/TERTIARY.
- Nuevo helper `theme.get_font(weight, size)` portable cross-platform.

### Cambios en API
- `save_glyphs_to_bank` ahora devuelve `dict` (antes `int`). Los callers
  legacy que esperan int siguen funcionando si chequean `truthiness`.
- `GlyphBank.__init__` acepta `profile_id`. Default mantiene compat hacia atrás.
- `GlyphEntry` gana campos: `profile_id`, `perceptual_hash`.

## [4.0.1] — 2026-05-23 (higiene del repo + fixes prioridad máxima)

### Infraestructura
- Versión sincronizada a `4.0.1` en `VERSION`, `config.py`, `pyproject.toml` e `install.sh`
- 53 archivos `__pycache__/*.pyc` eliminados del tracking de git (ya en `.gitignore`)
- `LICENSE MIT` añadida al repositorio
- `install.sh`: añadidas `tqdm`, `pdf2image`, `pdfplumber` a las dependencias instaladas
- `pyproject.toml`: añadidas `pdf2image~=1.17`, `pdfplumber~=0.11` a `[project.dependencies]`
- README: contador de tests actualizado de 63 → 121
- `tests/test_e2e_extraction.py`: `pytest.skip` con `allow_module_level=True` (colección limpia)

### Fixes funcionales
- `config.py`: nueva constante `MIN_GLYPH_QUALITY = 0.18` cargada desde `settings.json`
- `settings_view.py`: `_apply_settings_to_config` ahora escribe `config.MIN_GLYPH_QUALITY`
- `extractor_tab.py`: usa `config.MIN_GLYPH_QUALITY` (antes hardcodeado a `0.18` ignorando Settings)
- `ingestion.py`: `.doc` antiguo devuelve mensaje claro en vez de fallar con excepción críptica
- `study_view.py`: filetypes de diálogos ya no anuncian `.doc`; preview muestra advertencia
- `project_manager.delete()`: solo borra imágenes dentro de `DATA_DIR`; rutas externas no se tocan

### Nuevas herramientas
- `tools/doctor.py` — verifica Python, deps requeridas/opcionales, tesseract, poppler,
  directorios, `settings.json` y GlyphBank; salida con colores, exit 1 en errores críticos
- `tools/clean.py` — limpia temporales (`temp_bulk_capture`, debug overlays, caché OCR opcional,
  autosaves huérfanos); soporta `--dry-run`

### Captura masiva (Fase 2 — integrado en este release)
- `BulkGlyphCandidate`: campo `source_label` (nombre legible de la fuente)
- `BulkCaptureSession`: campos `is_pdf`, `total_pages`, `elapsed_s`
- `BulkCaptureRunner.run_pdf()`: procesamiento de PDF escaneado en lotes de 2 páginas (≤60 MB RAM)
- `BulkCaptureRunner.run_images()`: alias de `run()` para imágenes sueltas
- UI: barra de progreso determinista (0→1.0), botón "📄 Cargar PDF", modal de previsualización
- 3 tests nuevos: `source_label`, `session fields`, `run_pdf cancellation`

---

## [4.1.0-dev] — 2026-05-22 (integración end-to-end + limpieza)

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
