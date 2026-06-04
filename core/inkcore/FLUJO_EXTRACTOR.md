# Flujo único del extractor de glifos "Mi Letra"

Mapa de cómo queda el extractor tras las tandas A–C (reparación) + 4ª/5ª
(exactitud y consolidación). Punto de entrada único, legacy como fallback.

## Diagrama

```
extract_from_image(image_path, reference_text, opts)         ← ENTRADA ÚNICA
│
├─ use_pipeline = True (default, F6)
│   │
│   ▼
│  GlyphExtractionPipeline.extract(image_path, reference_text)
│   │   cfg = _build_default_pipeline_config()  ← detectores desde config.GLYPH_DETECTOR (Paso 3)
│   │
│   ├─ 1. imread_oriented()            EXIF (F5)
│   ├─ 2. orient_by_content()          orientación 0/90/180/270: manual → OSD → no-op (Paso 2)
│   ├─ 3. _scale / _autocrop / _deskew preprocesado geométrico
│   ├─ 4. detectores → best_binary()   multibinarización adaptativa (Salto 5)
│   │                                  classic_cv + (neuronal si está, fusión F8)
│   ├─ 5. fuse()                       union / intersection(consenso) / cascade(Y-aware) (F8)
│   ├─ 6. filtro forma/cobertura
│   ├─ 7. crops PIL en memoria         (sin re-leer disco, F10)
│   ├─ 8. labelers en batch            tesseract + trocr
│   ├─ 9. expected_map                 caja↔char de la referencia:
│   │                                    "positional" (default) | "dp" Needleman-Wunsch (Salto 3)
│   ├─ 10. vote(consensus) + is_verified + classify_tier_verified
│   │        GOLD ⇔ calidad alta ∧ consenso labelers ∧ char == referencia (F4)
│   ├─ 11. wf_calibration.record_many  aprende anchos de glifos verificados (Salto 4)
│   ├─ 12. demote_session_outliers     consenso entre instancias del mismo char (Salto 2)
│   └─ 13. guarda a disco SOLO los aceptados (F10-A)
│   │
│   ├─ glifos > 0  → devuelve (camino real)
│   └─ glifos == 0 o excepción ──┐
│                                 │  FALLBACK
└─ use_pipeline = False ─────────┤
                                  ▼
                          GlyphExtractor._run()   ← LEGACY (vivo, probado)
                          imread_oriented + orient_by_content + segmentación por
                          proyección guiada por la referencia. Sigue disponible.
```

## Decisiones de diseño clave

- **Gold = exactitud, no cantidad.** Un glifo es Gold solo si: calidad alta ∧
  los labelers tienen consenso ∧ el char coincide con la referencia. En letra
  manuscrita real eso es exigente (tesseract de imprenta rara vez acuerda con
  trocr), así que muchos glifos quedan **Silver** — y se guardan y usan igual.
  Es deliberado: preferimos pocos Gold confiables a muchos Gold falsos.
- **El legacy NO se borró.** Es el fallback automático (0 glifos o excepción) y
  se prueba (`test_pipeline_legacy_equivalence`, `test_e2e_extraction`).
- **Fuente única de verdad del detector:** `config.GLYPH_DETECTOR` (Paso 3).
- **Selección de glifo del banco:** medoide determinista por defecto
  (`get_best_glyph`), variación al azar para el renderer (Salto 2).

## Saltos DENTRO del pipe vs FUERA

| Salto / Paso | Estado | Default |
|---|---|---|
| S0 evaluación (tools/eval) | dentro | — |
| S1 CRAFT/Paddle | **fuera** | no instalados; classic_cv |
| S2 consenso/medoide | dentro | activo |
| S3 alineación DP | dentro | **opt-in** (`char_alignment="dp"`); positional default |
| S4 calibración wf | dentro | activo |
| S5 multibinarización | dentro | activo |
| Paso 2 orientación | dentro | manual + OSD (auto al instalar osd.traineddata) |
| Paso 3 fuente única detector | dentro | activo |

## Cómo medir (tools/eval)

```bash
python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label miprueba
```
Requiere `<img>.gt.json` con cajas reales anotadas sobre `<img>.preprocessed.png`
para IoU / char-accuracy / gold-precision. Ver `tools/eval/README.md`.

## Pendientes conocidos

- **osd.traineddata** no instalado → la orientación automática espera; usar
  `manual_orientation` mientras tanto. (`sudo dnf install tesseract-langpack-osd`)
- **Ground-truth** sin anotar → IoU/char-accuracy/gold-precision no medibles aún;
  validación por conteo de cajas + inspección.
- **DP como default**: requiere medir contra ground-truth para decidir si gana al
  posicional. Hoy opt-in.
```
