# Resultados del plan de precisión del extractor

Resumen honesto del trabajo en la rama `extractor-precision` (worktree). Base:
`worktree-reparacion-extractor` (8d5ca9d), que es un superset de `main`.

## Qué quedó hecho (con o sin número)

| Fase | Qué | Estado / número |
|------|-----|-----------------|
| 0 | Aparato de medición | `bootstrap_gt.py` (siembra GT semi-auto), `PRECISION_LOG.md`, `test_eval_harness.py`. `run_eval` ya existía. **Sin GT real aún → IoU/char-acc/gold-prec no medibles.** |
| 1 | Locking del banco | `get_review_queue` y `get_bank_report` ahora toman snapshot bajo `_bank_lock`. Fix de crash real; no afecta exactitud. |
| 2 | Fusión multi-detector configurable | `config.GLYPH_DETECTOR_FUSION` + `GLYPH_DETECTORS_EXTRA` + UI. **Default conservador (`[]`) → comportamiento idéntico (258 tests verdes).** |
| 3 | TrOCR handwritten | Modelo configurable (`config.TROCR_MODEL`, small/base/large) resuelto en runtime + comandos de instalación CPU. **Verificado: base ya cacheado en disco, 2ª corrida offline.** |
| 4 | EasyOCR cascade | cascade ahora usa las cajas neuronales como **máscara de región** y classic_cv como caracteres (filtra ruido). **Medido sin GT: cascade 39→30 cajas (−23%) y 2× más rápido que union.** Default conservador. |
| 5 | Variantes / dedup | Instrumentación `variant_distribution()`. **Medido: 0 rechazos de dedup en muestra real → NO se tocaron umbrales** (sería optimización sin evidencia). |

## Qué mejoró con número

- **Concurrencia (Fase 1):** eliminado un `RuntimeError: list changed size during
  iteration` latente en dos lectores del banco. (Correctitud, no exactitud.)
- **Fusión cascade (Fase 4), medido sin GT en 1 muestra real:** la máscara de
  región filtra ruido — bajó de 39 a 30 cajas y corrió en 74 s vs 156 s de union.
  Confirma la *dirección* del diseño, pero **si esas 9 cajas eran ruido o
  caracteres reales solo lo dirá el GT anotado.**

## Qué NO se pudo medir (y por qué)

- **IoU / char-accuracy / gold-precision:** requieren `eval_dataset/*.gt.json`
  anotado sobre imágenes reales. No existe todavía (el dataset lo pone el usuario).
  Sin él, la métrica que más importa (gold-precision) no es calculable.
- **El delta real de EasyOCR y de TrOCR sobre la exactitud:** ambos están listos y
  funcionan, pero decidir si *suben gold-precision* en TU letra necesita GT.
- **Variantes por char con etiqueta correcta:** sin `reference_text`, 38/39 glifos
  salen como `'?'`. El conteo de variantes "reales" necesita referencia o plantilla.

## Defaults que quedaron activos (conservadores a propósito)

- `GLYPH_DETECTOR = "classic_cv"` (sin cambios).
- `GLYPH_DETECTORS_EXTRA = []` → EasyOCR **apagado** por defecto.
- `GLYPH_DETECTOR_FUSION = "cascade"` (solo aplica si hay >1 detector).
- `TROCR_MODEL = "microsoft/trocr-base-handwritten"`.
- `_dup_thresholds` y `MIN_GROUP=4` **sin cambios** (la medición no justificó tocarlos).

## Qué queda pendiente

1. **Anotar 5–10 imágenes reales** (`tools/eval/bootstrap_gt.py` → corregir →
   `run_eval`). Es el bloqueante #1: desbloquea todas las métricas.
2. Correr el **protocolo de la Fase 4** (base vs easyocr+cascade vs easyocr+union)
   y fijar el default ganador por número.
3. Medir el **delta de gold-precision con/sin TrOCR** sobre el GT.
4. Con `reference_text`/plantilla, verificar el objetivo de **≥5 variantes** por
   char frecuente y recién entonces decidir si aflojar el dedup.
5. (Opcional) Probar Paddle como tercer detector.

> Filosofía respetada: cada palanca neuronal queda **lista pero conservadora** hasta
> que un número de `run_eval` sobre la letra real confirme que gana. Preferimos pocos
> Gold confiables a muchos Gold falsos.
