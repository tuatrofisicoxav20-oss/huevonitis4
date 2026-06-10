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

## Protocolo de calibración (R4) — la página patrón

1. **Qué escribir.** En una hoja como las que usás de verdad (carpeta con
   renglones), escribí a mano 5-8 líneas con un pangrama español repetido o
   variado, que cubra ñ, acentos, mayúsculas y números, p. ej.:

   > El veloz murciélago hindú comía feliz cardillo y kiwi. La cigüeña
   > tocaba el saxofón detrás del palenque de paja. Año 2026: ¡qué
   > extraño! 0123456789.

   Escribí NATURAL, a tu velocidad normal — la calibración mide tus
   varianzas reales; si escribís "bonito" el render saldrá más robótico
   que tu letra de verdad.

2. **Cómo escanear/fotografiar.** Luz pareja, hoja derecha (<1° de giro),
   ≥150 DPI (foto de cel a página completa sirve). Sin sombras de mano.

3. **Calibrar el perfil:**

   ```bash
   python -m tools.calibrate_profile pagina_real.png --profile default
   ```

   Esto escribe `tipografia/{perfil}/calibration.json`. El Writer lo usa
   automáticamente (verás "🎯 calibrado con tu letra").

4. **Cerrar el loop A/B:** renderizá la MISMA frase y comparala:

   ```bash
   python -m tools.eval_render.compare real.png synth.png
   ```

   Lo que salga ❌ es trabajo pendiente; cambiá UNA cosa y volvé a medir.

## Línea base

`tests/test_render_realism.py` registra las métricas del renderer ACTUAL
sobre un banco stub con seed fija. Esos números son la línea base que las
fases siguientes deben mover (height_cv ↑, word_gap_cv ↑, autocorr ↑,
dup_rate ↓). El test se actualiza en cada fase que cambia el render.
