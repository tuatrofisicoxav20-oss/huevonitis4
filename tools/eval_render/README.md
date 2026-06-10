# eval_render — harness de realismo del render manuscrito

`tools/eval` mide al **extractor** (IoU de glifos). Este paquete mide al
**renderer**: qué tan humana se ve una página de texto, real o sintética
(R-BUG-12). Es la base del loop de las fases R0–R9:

> medir → cambiar UNA cosa → volver a medir → commit.

## Uso

```bash
# Métricas de una imagen suelta
python -c "from tools.eval_render.metrics import metrics_from_path as m; \
           import json; print(json.dumps(m('pagina.png'), indent=2))"

# Comparación real vs sintético (tabla con veredicto ±30%)
python -m tools.eval_render.compare real.png synth.png
python -m tools.eval_render.compare real.png synth.png --json resultado.json
```

## Métricas (metrics.py)

| métrica | qué mide | referencia humana |
|---|---|---|
| `height_cv` | CV de alturas de caja de letra | 0.35–0.60 (asc/desc reales) |
| `letter_gap_mu/sigma/cv` | huecos entre letras de la misma línea | CV > 0 |
| `word_gap_mu/sigma/cv` | huecos de palabra (> 2.5× mediana) | CV > 0.10 |
| `baseline_sigma` | σ del residuo del y-inferior vs la recta de línea | > 0 (no láser) |
| `baseline_autocorr` | autocorrelación lag-1 del residuo | > 0.4 (paseo, no ruido) |
| `slant_mean/std` | inclinación por momentos de imagen | deriva suave |
| `phash_dup_rate` | fracción de letras con un gemelo perceptual (dHash ≤ 6) | < 0.05 |

La segmentación es por componentes conexos (Otsu + union-find NumPy puro,
sin cv2), con agrupación en líneas por centro vertical y fusión de
diacríticos (punto de la i / tilde) con su letra base.

## Protocolo A/B (resumen; el protocolo completo llega con R4)

1. Escribí a mano una **frase patrón** en papel real: pangrama español con
   ñ, acentos, mayúsculas y números. Escaneala/fotografiala igual que el
   output sintético.
2. Renderizá la MISMA frase con Huevonitis a tamaño aparente igual.
3. `python -m tools.eval_render.compare real.png synth.png`
4. Lo que salga ❌ es trabajo pendiente; las fases R1–R9 lo van moviendo.

## Línea base

`tests/test_render_realism.py` registra las métricas del renderer ACTUAL
sobre un banco stub con seed fija. Esos números son la línea base que las
fases siguientes deben mover (height_cv ↑, word_gap_cv ↑, autocorr ↑,
dup_rate ↓). El test se actualiza en cada fase que cambia el render.
