# Roadmap — Huevonitis 4

Releases planeados. Cada uno tiene un objetivo claro y delimitado.

## 4.1.1 — Release Cleanup (actual)

**Objetivo:** limpiar repo, sincronizar versiones, asegurar borrado de archivos,
crear herramientas de diagnóstico/limpieza.

- ✅ Versión sincronizada en todos los archivos
- ✅ `.pyc/__pycache__` removidos del tracking
- ✅ `LICENSE` MIT
- ✅ `pdf2image`, `pdfplumber`, `tqdm` añadidos a install.sh / pyproject.toml
- ✅ `tools/doctor.py` y `tools/clean.py`
- ✅ Borrado restringido a `DATA_DIR` y `bank_dir`
- ✅ `min_glyph_quality` conectado al extractor
- ✅ `.doc` antiguo deja de fingir compatibilidad
- ✅ KNOWN_ISSUES, ARCHITECTURE, ROADMAP, RELEASE_CHECKLIST

## 4.1.2 — Safety Cleanup

**Objetivo:** eliminar warnings, reducir `except Exception` críticos, mejorar
mensajes de error de UI.

- [ ] Reducir `except Exception` en `extractor.py` y `renderer.py`
- [ ] Cambiar `Image.Image.getdata()` por API compatible con Pillow futuro
- [ ] Resolver deprecations actuales de pytest
- [ ] Manejo visual de errores en todas las vistas (toast unificado)
- [ ] Cancelación visible en operaciones largas (OCR, bulk capture)
- [ ] Modo seguro (deshabilita backends no instalados con tooltip explicativo)

## 4.2 — OCR Test Upgrade

**Objetivo:** suite completa de OCR con fixtures reales.

- [ ] Fixtures reales en `tests/fixtures/ocr/`
- [ ] `expectations.json` con casos reales para PDF texto / escaneado / mixto
- [ ] Tests por cada backend (tesseract, paddleocr, easyocr, doctr)
- [ ] Tests de invalidación de caché ante cambio de archivo fuente
- [ ] Migración de caché OCR de pickle a JSON o SQLite (eliminar `pickle.load`)
- [ ] Tests de folder ingestion con orden estable

## 4.3 — Extractor Hardening

**Objetivo:** dividir `extractor.py` en módulos manejables y subir robustez.

- [ ] Separar `_align_pos`, `_test_all_strategies`, `_extract_pass`,
      `_align_dp_energy`, `_tesseract_boundaries`, `_align_cc_first`
- [ ] Perfiles de preprocesamiento (sombra, bajo contraste, papel rayado)
- [ ] Benchmark real con `tools/compare_strategies.py` mejorado
- [ ] Pruebas de regresión legacy vs ensemble (mismo score con misma imagen)
- [ ] Mejora de deskew y eliminación de líneas

## 4.4 — UI Reliability

**Objetivo:** matar todos los congelamientos y dejar la UI 100% responsiva.

- [ ] Workers en todas las operaciones >300ms (extracción, OCR, render, export)
- [ ] Barra de progreso real (no indeterminada) donde se pueda
- [ ] Panel de diagnóstico integrado en Settings (`tools/doctor.py` como vista)
- [ ] Métricas en vivo: detector usado, calidad promedio, glifos rechazados
- [ ] Preview de cajas detectadas antes de aprobar
- [ ] Cola de revisión mejorada — aprobar/rechazar con teclado

## 4.5 — Writer Realism

**Objetivo:** generador de escritura visualmente más natural.

- [ ] Variación de tamaño / inclinación / presión por glifo
- [ ] Variación entre líneas (no toda la página idéntica)
- [ ] Espaciado entre letras y palabras con jitter aleatorio
- [ ] Plantillas: hoja blanca, rayada, cuadriculada, libreta con margen
- [ ] Vista previa antes de exportar
- [ ] Mejora de exportación PDF (multipágina, márgenes correctos)

## 5.0 — IA + Tletl + Crotolamo

**Objetivo:** integración real de IA (clasificador ML) y nuevos módulos.

- [ ] Clasificador ONNX real (reemplaza `FallbackGlyphClassifier`)
- [ ] Tletl: módulo de traducción/translit
- [ ] Crotolamo: módulo TBD
- [ ] Pipeline IA documentado en `docs/ai-integration-notes.md`

---

## No hacer todavía

- ❌ No meter más features grandes hasta cerrar 4.1.2
- ❌ No reescribir todo el extractor de golpe — separar por método con tests
- ❌ No empaquetar como release final hasta que la cobertura de OCR/UI suba
- ❌ No publicar zip "definitivo" con `.git/`, `__pycache__/`, etc.
- ❌ No confiar en los 127 tests actuales como cobertura completa
- ❌ No tocar módulos estables sin tests primero
