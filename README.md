# Huevonitis 4

App de escritorio Python para producir apuntes escolares con tu letra real y gestionar el negocio freelance.

## Características

- **InkCore** — extrae tu letra de fotos y renderiza texto con ella
- **Proyectos** — editor de páginas con canvas, undo/redo, exportación PNG/PDF
- **Estudio** — importa texto/Word, genera resumen, flashcards y quiz automáticos
- **Negocio** — cotizaciones en MXN, registro de pagos, dashboard de ingresos
- **Config** — ajustes persistentes (precio base, autosave, Tesseract)

## Arquitectura

```
huevonitis 4/
├── main.py                   # Entrada — carga config, inicializa módulos, lanza app
├── config.py                 # Constantes globales y carga de settings.json
├── app_state.py              # Estado compartido entre vistas (current_project, etc.)
├── core/
│   ├── models.py             # Dataclasses SSOT: Project, ClientJob, Payment, Glyph…
│   ├── serializer.py         # JSON ↔ dataclasses
│   ├── project_manager.py    # CRUD de proyectos con escritura atómica + .bak
│   ├── diagnostics.py        # Colector de diagnósticos y tiempos
│   ├── businesscore/
│   │   ├── estimator.py      # Cálculo de precio MXN (urgencia × tipo × páginas)
│   │   ├── ledger.py         # CRUD de trabajos y pagos con persistencia JSON
│   │   └── models.py         # Re-exporta desde core.models; constantes de listas
│   ├── export/
│   │   └── pdf_exporter.py   # Exporta texto e imágenes a PDF (ReportLab)
│   ├── inkcore/
│   │   ├── extractor.py      # GlyphExtractor — pipeline completo de extracción
│   │   ├── extractor_preprocess.py  # ImagePreprocessor (desacoplado)
│   │   ├── extractor_segments.py   # SegmentDetector (desacoplado)
│   │   ├── bank.py           # GlyphBank — almacén persistente de glifos con dedup
│   │   ├── pipeline.py       # InkCorePipeline — orquesta extractor + banco + renderer
│   │   ├── renderer.py       # HandwritingRenderer — renderiza texto con glifos
│   │   ├── reporter.py       # InkCoreReporter — informe PDF/modal del banco
│   │   ├── quality.py        # assess_glyph — scoring de calidad
│   │   └── ai/               # FallbackGlyphClassifier (reglas); hooks para ONNX
│   ├── ocr/
│   │   └── engine.py         # OCREngine — Tesseract + lectura de .docx
│   └── studycore/
│       ├── builder.py        # build_study_bundle (resumen, flashcards, quiz) + caché
│       └── models.py         # Re-exporta Flashcard/QuizQuestion/StudyBundle
├── ui/
│   ├── theme.py              # Colores, tipografía, init_fonts() portable
│   ├── app.py                # HuevonitisApp (CTk root, sidebar, vistas)
│   ├── animations.py         # count_up y helpers de animación
│   ├── components/
│   │   ├── canvas_editor.py  # Editor de canvas con undo/redo y caché de imágenes
│   │   ├── card.py           # ProjectCard con stripe de estado
│   │   ├── sidebar.py        # CollapsibleSidebar
│   │   └── toast.py          # ToastManager
│   └── views/                # Una vista por sección de la app
├── tools/
│   ├── compare_strategies.py # CLI para comparar estrategias de segmentación
│   ├── doctor.py             # Diagnóstico de entorno (deps, dirs, settings)
│   ├── clean.py              # Limpieza de temporales (--dry-run disponible)
│   └── measure_fixture.py    # Genera expectations.json desde una imagen real
├── docs/
│   ├── ARCHITECTURE.md       # Arquitectura, módulos y flujos clave
│   ├── ROADMAP.md            # Releases planeados (4.1.1 → 5.0)
│   ├── RELEASE_CHECKLIST.md  # Lista a recorrer antes de publicar
│   ├── CHANGELOG.md
│   ├── KNOWN_ISSUES.md
│   └── ai-integration-notes.md  # Guía para integrar clasificador ONNX real
├── tests/                    # pytest — 127 tests
├── requirements.txt
├── requirements-optional.txt # Backends extras (PaddleOCR, TrOCR, EasyOCR)
├── pyproject.toml            # ruff + pytest config
├── install.sh                # Instalador para Fedora/Ubuntu/Arch
├── uninstall.sh
└── LICENSE                   # MIT
```

## Instalación

### Fedora / Ubuntu / Arch (recomendado)

```bash
bash install.sh
```

Crea un entorno virtual en `~/.local/share/huevonitis4/env`, instala todas las
dependencias y registra la app en el menú del sistema.

### Manual

```bash
pip install -r requirements.txt
# Tesseract + Poppler
sudo dnf install tesseract tesseract-langpack-spa poppler-utils   # Fedora
sudo apt install tesseract-ocr tesseract-ocr-spa poppler-utils    # Ubuntu
python3 main.py
```

### Verificar el entorno

```bash
python tools/doctor.py
```

Muestra qué dependencias faltan, si tesseract/poppler están en el PATH, y el
estado de los directorios de datos.

## Tests

```bash
pytest -q
```

127 tests, ~2 segundos. Solo tests de lógica core — UI no incluida.

## Datos de usuario

Guardados en `~/.local/share/huevonitis4/`:
- `projects/` — archivos JSON de proyectos
- `tipografia/` — banco de glifos (PNGs + `_manifest.json`)
- `business/` — trabajos y pagos (`jobs.json`, `payments.json`)
- `settings.json` — configuración persistente
- `app.log` — log de la aplicación
- `temp_bulk_capture/`, `debug_extractions/` — limpiables con `python tools/clean.py`

## Licencia

MIT — ver [LICENSE](LICENSE).
