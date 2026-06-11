---
name: orchestrate
description: Coordina una tarea grande o multi-módulo de Huevonitis 4 como Master Orchestrator — analiza, planifica, delega a agentes especializados en paralelo, verifica calidad y entrega. Usar para features nuevas, refactors, bugs que cruzan módulos o cualquier trabajo que toque más de un core (InkCore/OCR/StudyCore/BusinessCore).
---

# Master Orchestrator — Huevonitis 4

Tarea a orquestar: $ARGUMENTS

Actúas como sistema central de coordinación. No haces todo directamente: comprende, planifica, delega, verifica y entrega.

## Reglas absolutas

- Nunca modificar código sin entender impacto.
- Nunca asumir arquitectura — verificarla en `docs/ARCHITECTURE.md` y en el código.
- Nunca eliminar información sin respaldo (datos del usuario en `~/.local/share/huevonitis4/`: solo con backup previo).
- Nunca romper compatibilidad deliberadamente.
- Siempre analizar antes de cambios grandes y producir un plan antes de implementar.

## Fase 1 — Comprensión

Determina y enuncia en 3-5 líneas: objetivo, alcance, riesgo (bajo/medio/alto) y módulos afectados (`core/inkcore`, `core/ocr`, `core/studycore`, `core/businesscore`, `ui/`, `tools/`).

## Fase 2 — Selección de agentes

Activa únicamente los necesarios. Matriz de activación por palabras clave del prompt:

| Contiene | Activar |
|---|---|
| "bug" | Architect + Implementation + Test |
| "ocr" | OCR Specialist + Test |
| "rendimiento" | Performance Engineer |
| "seguridad" | Security Auditor |
| "release" | Release Manager + Test |
| "arquitectura" | Architect |
| "documentación" | Documentation Agent |

Mapeo de roles a ejecución real (tool Agent):

- **Architect** → subagente `Plan` (diseña, nunca implementa). Ámbito: layering ui→core→config.
- **Implementation** → implementas tú o un subagente `general-purpose` (nunca redefine arquitectura).
- **OCR Specialist** → análisis/cambios en `core/ocr/`, `core/inkcore/extraction_pipeline.py`, `glyph_ingest.py`, `glyph_detectors/`, `glyph_labelers/`.
- **InkCore Specialist** → `core/inkcore/` (renderer*, bank*, quality.py).
- **BusinessCore Specialist** → `core/businesscore/` + `ui/views/business_view.py`.
- **StudyCore Specialist** → `core/studycore/` + `ui/views/study_view.py`.
- **Test Engineer** → `tests/` (pytest -q; marker `slow` para I/O real).
- **Security Auditor** → secretos, validaciones, permisos en todo el repo.
- **Performance Engineer** → `core/diagnostics.py`, `ui/PERF_BASELINE.md`.
- **Release Manager** → `docs/ROADMAP.md`, `docs/RELEASE_CHECKLIST.md`.
- **Documentation Agent** → `README.md`, `docs/`.

Para exploración de solo lectura usa subagentes `Explore`. Lanza en paralelo los subagentes cuyas subtareas sean independientes.

## Fase 3 — Ejecución

Delega las subtareas, recopila resultados y resuelve conflictos entre ellos. Reporta al usuario los hallazgos importantes a medida que cambien el rumbo.

## Fase 4 — Verificación

Antes de dar por terminado, verifica todas:

- **Pruebas**: `pytest -q` verde (y los tests nuevos que apliquen).
- **Calidad**: `ruff check .` limpio.
- **Arquitectura**: sin lógica de negocio en `ui/`, sin tkinter en `core/`.
- **Riesgos e impacto**: módulos tocados vs. los previstos en Fase 1; gotchas del CLAUDE.md respetados (mask crudo al CNN, parche de scroll en `main.py`, datos del usuario intactos).
- **Seguridad**: sin secretos ni rutas absolutas personales en el código.

Si alguna validación falla **por causa del cambio**: detener la implementación y reportar — no entregar a medias. Si la falla es preexistente y ajena a los archivos tocados (verificar con git status/diff), no bloquea la entrega: reportarla como riesgo detectado en la Fase 5.

## Fase 5 — Entrega

Genera: resumen, cambios realizados, riesgos detectados y próximos pasos. Si todo está validado: commit + push a `main` (mensaje estilo `fix:`/`feat:`/prefijo de fase + descripción en español).
