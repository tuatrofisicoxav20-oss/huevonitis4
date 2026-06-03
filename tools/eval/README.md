# Evaluador del extractor de glifos (Salto 0)

Infraestructura para **medir** la exactitud del extractor y comparar entre saltos.
Sin esto, cualquier cambio de extracción es fe ciega.

## Formato del ground-truth (`<nombre>.gt.json`)

Un JSON por imagen, junto a ella, con el mismo nombre base:

```json
{
  "image": "mi_foto.png",
  "reference_text": "hola mundo",
  "chars": [
    {"char": "h", "box": [x, y, w, h]},
    {"char": "o", "box": [x, y, w, h]}
  ]
}
```

- `box` = `[x, y, w, h]` en **píxeles**, sobre la imagen **PREPROCESADA**
  (ver abajo), no sobre la original.
- `char` = el carácter real de esa caja.
- `reference_text` (opcional) = el texto que se escribió, para activar la
  verificación cruzada del pipeline.

### ⚠ Coordenadas: anotar sobre la imagen PREPROCESADA

El extractor escala, recorta y endereza (deskew) la imagen antes de detectar.
Las cajas predichas viven en ese espacio transformado. Por eso, al correr
`run_eval` sobre una imagen, se emite `<nombre>.preprocessed.png`: **anotá el
ground-truth sobre esa imagen**, no sobre la original. Si no, el IoU no cuadra.

## Cómo llenar un dataset (mínimo 5 imágenes propias)

1. Poné tus fotos en `eval_dataset/` (`.png`/`.jpg`).
2. Corré una vez:
   ```bash
   python -m tools.eval.run_eval tools/eval/eval_dataset/mi_foto.png --label baseline
   ```
   Esto genera:
   - `mi_foto.preprocessed.png` → el espacio donde anotar.
   - `mi_foto.pred.json` → las predicciones del extractor como **punto de
     partida editable**.
3. Corregí `mi_foto.pred.json` (char + box reales), renombralo a
   `mi_foto.gt.json`.
4. Volvé a correr; ahora las métricas (IoU, char-accuracy, precisión de Gold)
   son reales.

> Para que las métricas signifiquen algo, rellená `eval_dataset/*.gt.json` con
> cajas reales de tus propias imágenes (**mínimo 5**). El `ejemplo_sintetico`
> incluido es solo un placeholder para que la herramienta corra sin crashear.

## Correr la evaluación

```bash
# Una o varias imágenes (acepta globs)
python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label salto3
```

Imprime una tabla por imagen + un agregado, y guarda un JSON en
`tools/eval/results/eval_<label>_<timestamp>.json`. Usá `--label` distinto por
salto (`baseline`, `salto1`, `salto3`…) para poder comparar corridas.

## Métricas

- **IoU medio**: solapamiento medio entre cajas predichas y GT (matching óptimo
  húngaro; cae a greedy si no hay scipy).
- **char-accuracy**: de las cajas bien matcheadas (IoU ≥ 0.5), fracción con el
  carácter correcto.
- **gold_rate**: fracción de glifos predichos marcados `Gold`.
- **gold_precision**: de los marcados `Gold`, cuántos están bien matcheados Y
  con el carácter correcto. **Esta es la métrica que más importa**: mide si
  "Gold" significa de verdad "correcto".

Sin ground-truth, `run_eval` no explota: reporta cuántas cajas predijo y emite
la plantilla `.pred.json`, pero deja IoU/accuracy en `N/A`.
