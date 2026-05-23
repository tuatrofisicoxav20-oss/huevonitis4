# Known Issues — Huevonitis 4

## Resueltos en 4.1.0

### ✅ Pipeline UI desconectada de `GlyphExtractor`
`_extract()` en `InkCoreView` ahora lee `use_pipeline`, construye `PipelineConfig`
vía `_get_pipeline_config()` y los pasa a `ExtractionOptions`. El toggle
"Usar pipeline avanzada" ya afecta la extracción real (A1).

### ✅ `invalidate()` del caché OCR borraba entradas ajenas
`OCRResultCache.invalidate(path)` ahora carga cada `.pkl`, compara
`os.path.abspath(doc.source_path)`, y elimina solo las entradas que coinciden.
Las entradas de otros documentos se conservan (hotfix OCR cache).

### ✅ Toast duplicado "Texto importado" en StudyView
`_on_ocr_done()` mostraba un toast redundante antes del toast detallado.
Eliminado; solo queda el toast de éxito con el resumen del texto (hotfix double toast).

### ✅ `build_study_bundle` — caché solo en memoria
Migrado a caché en disco con `shelve` + TTL 30 días en
`config.DATA_DIR / "study_bundle_cache"`. Persiste entre reinicios (B6).

---

## Pendientes

### Tema "Claro" — colores hardcodeados en algunos widgets
`ui/theme.apply_theme("light")` actualiza todas las constantes del módulo y
la opción "Claro" está disponible en Config. El cambio requiere reiniciar la app.
Los widgets con colores inline (`fg_color="#000000"`, fondos bulk-capture) pueden
no adaptarse completamente al tema claro; están marcados en el código con TODOs.

### extractor.py — reducción a <800 líneas pendiente
El objetivo era reducir `extractor.py` de 1875 a <800 líneas delegando métodos
de preprocesamiento a `ImagePreprocessor` y `SegmentDetector`. Se activaron los
imports y se renombraron/corrigieron los módulos auxiliares, pero la delegación
completa requiere alinear diferencias de nombres entre clases (ej. `filtered_mask`
vs `_filtered_mask`). Tamaño actual: ~1875 líneas.
`extractor_preprocess.py` y `extractor_segments.py` marcados como DEPRECATED
con `DeprecationWarning` — la delegación real queda pendiente para un ticket dedicado.

### Tests de UI — InkCore mixins no cubiertos
Los mixins de `ui/views/inkcore/` (`extractor_tab.py`, `bulk_capture_tab.py`,
`bank_tab.py`, `writer_tab.py`, `review_tab.py`) no tienen tests porque
construir widgets CTK requiere Xvfb o un mock de Tk. La lógica de negocio
(extracción, banco) está cubierta en otros tests.

### Tests de UI no incluidos
El test suite cubre solo lógica de negocio y serialización. Tests de
`CanvasEditor`, `InkCoreView`, `BusinessView`, etc. requieren un mock de Tk
(pytest-mock + CTk stub) o entorno headless (Xvfb).

### Instaladores Windows/macOS
La app está pensada para Linux (CustomTkinter, rutas posix). No hay `.exe`
ni `.app`. Requiere empaquetado con PyInstaller + CI multi-plataforma.

### Clasificador ONNX real
`FallbackGlyphClassifier` fue eliminado de `InkCoreView` (dead code — A5).
La integración real con un clasificador ML (ver `docs/ai-integration-notes.md`)
y la cola de revisión de glifos queda pendiente para un ticket futuro.

### `except Exception` restantes
Quedan ~100 usos de `except Exception` en la base de código (extractor.py,
renderer.py, ui/views/*). Los críticos en `ledger.py` y `project_manager.py`
fueron ya narroweados. El resto requiere análisis caso por caso.
