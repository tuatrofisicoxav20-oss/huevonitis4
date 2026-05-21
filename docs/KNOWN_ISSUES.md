# Known Issues — Huevonitis 4

## Pendientes de esta sesión

### Tema "Claro" no implementado
`SettingsView` tiene la opción "Sistema" pero el tema claro real de CustomTkinter
no está completo (colores de cards/sidebar no adaptan bien). La opción "Claro"
fue removida del menú. Requiere auditoría completa de `ui/theme.py`.

### extractor.py — reducción a <800 líneas pendiente
El objetivo era reducir `extractor.py` de 1875 a <800 líneas delegando métodos
de preprocesamiento a `ImagePreprocessor` y `SegmentDetector`. Se activaron los
imports y se renombraron/corrigieron los módulos auxiliares, pero la delegación
completa requiere alinear diferencias de nombres entre clases (ej. `filtered_mask`
vs `_filtered_mask`). Tamaño actual: ~1875 líneas.

### Tabs InkCore — migración a submódulos pendiente
`inkcore_{extractor,bank,writer,review}_tab.py` fueron eliminados ya que eran
placeholders. La lógica real vive en `inkcore_view.py`. Una migración real
requiere mover las ~600 líneas de `InkCoreView` a submódulos con tests de UI.

### Tests de UI no incluidos
El test suite cubre solo lógica de negocio y serialización. Tests de
`CanvasEditor`, `InkCoreView`, `BusinessView`, etc. requieren un mock de Tk
(pytest-mock + CTk stub) o entorno headless (Xvfb).

### Instaladores Windows/macOS
La app está pensada para Linux (CustomTkinter, rutas posix). No hay `.exe`
ni `.app`. Requiere empaquetado con PyInstaller + CI multi-plataforma.

### Clasificador ONNX real
`FallbackGlyphClassifier` usa heurísticas de imagen. Para un clasificador
basado en ML, ver `docs/ai-integration-notes.md`.

### `except Exception` restantes
Quedan ~100 usos de `except Exception` en la base de código (extractor.py,
renderer.py, ui/views/*). Los críticos en `ledger.py` y `project_manager.py`
fueron ya narroweados. El resto requiere análisis caso por caso.

### `build_study_bundle` — caché en memoria no persistente
El caché SHA-256 vive en memoria de proceso. Se invalida al reiniciar la app.
No es un problema crítico pero un caché en disco (shelve/sqlite) mejoraría
el arranque para textos grandes.
