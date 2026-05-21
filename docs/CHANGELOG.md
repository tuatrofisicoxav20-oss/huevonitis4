# Changelog — Huevonitis 4

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
