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

## Cómo anotar tu dataset (mínimo 5 imágenes propias)

Flujo recomendado: **foto → `bootstrap_gt.py` → corregir a mano → `run_eval`**.

1. Poné tus fotos en `eval_dataset/` (`.png`/`.jpg`).
2. Sembrá el borrador semi-automático (baja la anotación de ~1 h a ~5 min):
   ```bash
   python -m tools.eval.bootstrap_gt tools/eval/eval_dataset/mi_foto.png \
       --ref "el texto que escribiste"
   ```
   Esto genera:
   - `mi_foto.preprocessed.png` → el espacio sobre el que anotás.
   - `mi_foto.gt.json` → un **borrador editable** con las cajas + chars que el
     extractor predijo (o `mi_foto.gt.json.draft` si ya existía un GT, para no
     pisarlo).
3. Abrí `mi_foto.preprocessed.png` en un visor y corregí `mi_foto.gt.json`:
   arreglá los `char` mal asignados, ajustá las `box` mal puestas, borrá las
   cajas basura y agregá las letras que faltaron. Borrá los campos `tier` y
   `_nota`. (`bootstrap_gt.py` imprime estas instrucciones al final.)
4. Medí; ahora IoU, char-accuracy y precisión de Gold son reales:
   ```bash
   python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label baseline
   ```

> Alternativa sin `bootstrap_gt`: `run_eval` sobre una imagen sin GT también
> emite `mi_foto.preprocessed.png` y un `mi_foto.pred.json` editable; corregilo
> y renombralo a `mi_foto.gt.json`.

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
