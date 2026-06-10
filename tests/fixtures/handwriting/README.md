# Fixtures de letra manuscrita real

Este directorio contiene fotos/escaneos reales para tests end-to-end.

## Convención de nombres

`{n}_{descripcion}_{tier_esperado}.jpg`

- `n`: 01, 02, … (orden lexicográfico)
- `descripcion`: corto, snake_case (ej. `alfabeto_minus`, `frases_naturales`)
- `tier_esperado`: una palabra que indique calidad esperada (`alta`, `media`, `baja`)

Ejemplos:
```
01_alfabeto_minus_alta.jpg   → página 1 de la plantilla, calidad buena
02_numeros_media.jpg         → página 3, fotografía con luz mediocre
```

## Cómo añadir nuevos fixtures

1. Copia la imagen a este directorio con la convención de nombres.
2. Corre `python tools/eval/run_eval.py <ruta>` para medir la extracción
   contra el ground-truth.
3. Edita `expectations.json` poniendo los mínimos ~85% de lo medido
   (deja margen — varianza natural en numpy/cv2 puede ser ±5%).

## Nota sobre .gitignore

Imágenes > 5 MB están en `.gitignore`. Si tus fixtures pesan menos,
se pueden commitear para CI. `expectations.json` siempre se commitea.
