# Resultados del overhaul de realismo (R0–R9)

Métricas de `tools/eval_render/metrics.py` sobre el golden (banco stub de
proporciones naturales conocidas, página llena de 15 líneas, seed 42). La
columna "humano" es la referencia de la auditoría; "veredicto" compara el
estado final (R7 integrada: texturas de papel + anclaje a renglones) contra
ella.

| métrica | R0 (antes) | R2 | R3 | R5 | R7 (final) | humano | veredicto |
|---|---|---|---|---|---|---|---|
| `height_cv` | 0.20 | **0.30** | 0.31 | 0.30 | 0.30 | > 0.30 | ✅ |
| `word_gap_cv` | 0.04 | 0.08 | **0.125** | 0.129 | 0.150 | > 0.10 | ✅ |
| `baseline_autocorr` | −0.10 | −0.05 | **0.43** | 0.43 | 0.456 | > 0.40 | ✅ |
| `phash_dup_rate` | 0.77 | 0.71 | 0.80 | **0.04** | 0.004 | < 0.05 | ✅ |

Qué movió cada aguja (una cosa por ciclo, medida antes y después):

- **R2 — `height_cv` 0.20 → 0.30.** Escala proporcional por glifo
  (`nat_h/em · font_size`, R-BUG-01) + baseline real medido (R-BUG-02) +
  solape leve entre letras (el clamp a ≥1px impedía que las letras se
  rocen como en escritura real).
- **R3 — `word_gap_cv` 0.04 → 0.125.** Espacio de palabra gauss truncada
  (E1) en vez de constante (R-BUG-05).
- **R3 — `baseline_autocorr` −0.10 → 0.43.** El residuo de la línea base
  pasó de ruido blanco (jitter i.i.d. por letra) a procesos OU
  correlacionados (drift de muñeca + jitter heredado); la métrica usa
  ajuste robusto para que las colas de descendentes no ahoguen la señal.
- **R5 — `phash_dup_rate` 0.77 → 0.04.** Warp elástico por instancia
  (malla 4×4, borde anclado, 8% del alto) + deriva OU de tamaño/slant.
  El detector se recalibró con páginas de control: dHash 16×16 umbral ≤8
  separa sello puro (0.97) / variación humana redibujada (0.03); el dHash
  64-bit clásico era ciego (0.79 para variación genuina). El test es
  bilateral: con el pipeline apagado el detector debe seguir viendo ≥0.85.

## Criterios globales del plan

- ✅ Suite completa verde en cada checkpoint (R0→R9).
- ✅ Mismo seed → mismo PNG byte a byte (RNG inyectado, R3; test).
- ✅ Ningún carácter cae a fuente de sistema sin aviso: se OMITE y se
  reporta antes de exportar (H8); placeholder rojo solo en preview.
- ✅ Texto de 500 palabras sin perder un solo glifo (contador, R2).
- ✅ Manifests v1 sin métricas cargan y renderizan en modo estimado (R1).
- ✅ PDF multipágina sin reportlab (Pillow nativo, R8) con tamaño físico
  carta exacto (MediaBox 612×792).
- ✅ Tiempos: render R6 completo (supersampling 2× + pase de tinta) =
  2.15× el render previo (límite del plan: 2.5×).

## Pendiente del usuario (no automatizable)

1. **Calibrar con TU letra**: escribir la página patrón (protocolo en
   `tools/eval_render/README.md`) y correr
   `python -m tools.calibrate_profile pagina.png` — las varianzas dejan de
   ser defaults razonables y pasan a ser las tuyas.
2. **Comparar real-vs-synth**: `python -m tools.eval_render.compare
   real.png synth.png` con la misma frase en ambas. Lo que salga ❌ se
   ajusta con UNA perilla por ciclo (las opciones de RenderOptions están
   documentadas campo por campo).
3. **Mini test de Turing**: `python -m tools.eval_render.ab_sheet real.png
   "texto" --out hoja.png` y mostrar la hoja (sin el JSON) a 5-10
   personas. Meta: ≤60% de acierto.
