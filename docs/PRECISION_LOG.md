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

## Comando de rollback por fase

Cada fila de arriba corresponde a uno o más commits. Para revertir una fase:

```bash
git log --oneline            # localizar el/los commit(s) de la fase
git revert <sha>             # revertir sin reescribir historia
```

## Protocolo de medición (se completa al instalar deps / anotar GT)

Ver más abajo conforme avancen las fases 3, 4 y 5.
