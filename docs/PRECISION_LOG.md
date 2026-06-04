# PRECISION_LOG — Marcador de exactitud del extractor

Bitácora de cada fase del plan de precisión. **Regla de oro:** ninguna fase se
considera "mejor" sin un número de `run_eval` que lo respalde. Si una mejora no
es medible todavía (p. ej. falta ground-truth anotado), se escribe explícitamente
"no medible aún" + por qué, en vez de afirmar que mejoró.

Las métricas salen de `python -m tools.eval.run_eval <imgs> --label <fase>`:

- **IoU**: solapamiento medio caja-predicha ↔ caja-GT (matching húngaro).
- **char-acc**: de las cajas bien matcheadas (IoU ≥ 0.5), fracción con char correcto.
- **gold-prec**: de los glifos marcados Gold, cuántos están bien matcheados Y con
  char correcto. **La métrica que más importa** (mide si "Gold" = "correcto").

> ⚠ Bloqueante de medición: hace falta un `eval_dataset/*.gt.json` anotado sobre
> imágenes reales (mínimo 5). Mientras no exista, IoU/char-acc/gold-prec quedan en
> "n/m" (no medible) y solo se reportan señales parciales (nº de cajas, gold_rate,
> variantes/char, timing). Ver `tools/eval/README.md` → "Cómo anotar tu dataset".

## Tabla

| fase | fecha | IoU | char-acc | gold-prec | detectores | labelers | notas |
|------|-------|-----|----------|-----------|------------|----------|-------|
| 0 (baseline) | 2026-06-04 | n/m | n/m | n/m | classic_cv | tesseract(+trocr si instalado) | aparato de medición listo; falta GT real anotado |
| 1 (locking) | 2026-06-04 | n/m | n/m | n/m | classic_cv | — | fix de concurrencia, no afecta exactitud. Rollback: `git revert 5ab96ab` |
| 2 (fusión config) | 2026-06-04 | = baseline | = baseline | = baseline | classic_cv (default) | — | solo plumbing; con GLYPH_DETECTORS_EXTRA=[] el comportamiento es idéntico (247 tests verdes). Rollback: `git revert d1a86c3 7c86405 5032430 c16e713` |

## Comando de rollback por fase

Cada fila de arriba corresponde a uno o más commits. Para revertir una fase:

```bash
git log --oneline            # localizar el/los commit(s) de la fase
git revert <sha>             # revertir sin reescribir historia
```

## Protocolo de medición — EasyOCR cascade vs union (Fase 4)

**Bloqueante:** necesita `eval_dataset/*.gt.json` anotado (ver README). Con GT, el
experimento decide el default POR NÚMERO, no por intuición. EasyOCR ya está
instalado en este equipo; si no lo estuviera:

```bash
pip install torchvision --index-url https://download.pytorch.org/whl/cpu  # NMS
pip install easyocr
```

Correr los 3 casos y comparar IoU / char-acc / gold-prec:

```bash
# 1) Base: classic_cv solo (default actual)
#    settings.json: {"glyph_detectors_extra": []}
python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label base_classic

# 2) classic_cv + easyocr, fusión cascade (región-máscara)
#    settings.json: {"glyph_detectors_extra": ["easyocr"], "glyph_detector_fusion": "cascade"}
python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label easyocr_cascade

# 3) classic_cv + easyocr, fusión union
#    settings.json: {"glyph_detectors_extra": ["easyocr"], "glyph_detector_fusion": "union"}
python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label easyocr_union
```

**Decisión:** el que dé mayor char-acc y gold-prec (a IoU comparable) gana y se
fija en `config.GLYPH_DETECTORS_EXTRA` / `GLYPH_DETECTOR_FUSION`. Hasta entonces
el default queda conservador (`GLYPH_DETECTORS_EXTRA=[]`).

> ⚠ Expectativa templada (nota medida 2026-06 en requirements-optional.txt):
> EasyOCR/CRAFT agrupan por línea/palabra (2–4 cajas por hoja), NO por carácter.
> Por eso el modo cascade aquí usa esas cajas como MÁSCARA DE REGIÓN (filtra ruido
> de classic_cv fuera del texto), no como fuente de glifos. El cuello de botella
> real sigue siendo la segmentación de classic_cv, no la detección. La ganancia
> esperada de easyocr es sobre todo en gold-prec (menos basura marcada), no en
> número de glifos.

| caso | IoU | char-acc | gold-prec | n_pred medio | notas |
|------|-----|----------|-----------|--------------|-------|
| base_classic | (pendiente GT) | | | | |
| easyocr_cascade | (pendiente GT) | | | | |
| easyocr_union | (pendiente GT) | | | | |

### Observación SIN GT (señal parcial, no decisiva) — 2026-06-04

Corrida real sobre 1 muestra del usuario (WhatsApp 8.09.28), sin `reference_text`,
para validar la maquinaria end-to-end. **No mide exactitud** (Gold=0 en los tres
porque sin referencia no hay verificación char==ref → el tier tapa en Silver):

| caso | n_cajas | Gold | Silver | tiempo |
|------|---------|------|--------|--------|
| classic_cv solo | 39 | 0 | 35 | 115 s |
| classic+easyocr cascade | **30** | 0 | 30 | **74 s** |
| classic+easyocr union | 41 | 0 | 35 | 156 s |

Lectura: cascade **redujo** las cajas 39→30 (la máscara de región filtró ~23%,
coherente con descartar ruido de classic_cv fuera del texto) y fue ~2× más rápido
que union; union **infló** a 41 (sumó cajas de palabra de easyocr). Esto confirma
la *dirección* del diseño (cascade = filtro de ruido), pero si esas 9 cajas
filtradas eran ruido o caracteres reales **solo lo dirá el GT anotado**. Por eso
el default sigue conservador hasta medir gold-prec con `reference_text`.
