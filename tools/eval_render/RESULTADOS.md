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

## R14 — Estructura horizontal en prosa (H5, bloque CODE)

El estándar humano de R3 (autocorr > 0.40 con procesos OU) era SOLO del eje
vertical. H5 abre el eje horizontal estructural: margen izquierdo, sangría de
párrafo y respiración inter-párrafo. Instrumentación nueva en `metrics.py`
(`margin_autocorr`, `margin_sigma`, `indent_delta_mu/sigma`, `n_paragraphs`,
`right_ragged_cv`), con el mismo ajuste robusto en dos pasos que
`baseline_autocorr`; párrafos detectados desde la imagen por hueco vertical
> 1.6× el paso mediano. Tests sintéticos en `tests/test_metrics_horizontal.py`
(constante → ≈0; OU → >0.4; sangría conocida → recuperada).

**Antes (medido 02-jul, banco real de 1,174 glifos, prosa de 3 párrafos,
camino plano `render_pages`, seeds 42/7/101):**

| métrica | Limpio (clásico) | Escolar (snap) | humano | veredicto |
|---|---|---|---|---|
| `margin_autocorr` | −0.30 / −0.24 / −0.57 | 0.00 / −0.56 / −0.52 | > 0.40 | ❌ |
| `margin_sigma` (banda) | 0.5–1.0 px | 0.0–0.4 px | — | margen "de regla" |
| `indent_delta_mu` | −1.3…+0.7 px | 0.0…+0.3 px | sangría real acotada | ❌ inexistente |
| `right_ragged_cv` | 0.12–0.19 | 0.14–0.19 | ~0.2 sano | ✅ NO tocar |

Coincide con la medición externa de arranque (banda ~3px con 11/12 renglones,
autocorr ≈ −0.05 = ruido sobre constante, sangría inexistente). La σ externa
de 5.1 px era la σ CRUDA inflada por 1 renglón outlier; la banda robusta
(~1 px aquí, ~3 px externa) es la señal real. Causa raíz encontrada: el camino
snap (fondos rayados: Escolar/Examen) pega cada renglón con
`x = margin_left_px` FIJO (sin `_next_margin_offset`), y en el camino clásico
el walk OU de R3 queda en ±2 px finales tras el supersampling — por debajo del
ruido de cuantización. Nota: la autocorr con ~7 renglones de cuerpo es
ruidosísima; la validación de los ciclos C2 usa prosa larga (~24 renglones) y
varias seeds.

### R14 · C1-bis — correcciones del estimador (verificación adversarial)

Tres escépticos independientes ejecutando código real encontraron y confirmé:
(1) el detrend LINEAL de `margin_autocorr` se comía la energía de baja
frecuencia del propio OU y sesgaba el lag-1 hacia abajo (~1 de cada 3 páginas
genuinamente OU caía bajo 0.40) — pasó a residuo contra MEDIANA robusta, el
mismo criterio de la medición externa ("ruido blanco sobre constante");
(2) `_paragraph_starts` colapsaba cuando los huecos de párrafo eran ≥50% de
los pasos — el paso base pasó a la mediana de la MITAD BAJA (~p25), con test;
(3) `compare.py` daba veredicto relativo a métricas centradas en 0 —
`margin_autocorr` y los `indent_delta_*` pasaron a tolerancia absoluta, y
`n_paragraphs`/`right_ragged_cv` a informativas. ⚠ El estimador lag-1 por
página (~20 renglones) tiene varianza alta: validar siempre EN MEDIA sobre
varias seeds, nunca por página suelta.

### R14 · Ciclo C2.1 — deriva OU del margen izquierdo (perilla del ciclo)

Perilla: `margin_walk_rho` (nueva, correlación del OU, default 0.9) con σ
DERIVADA de amplitud y ρ (σ = 0.45·amp·√(1−ρ²)); antes σ iba fija en 2 px y
el walk quedaba en ±2 px finales tras el supersampling. El walk aplica ahora
también al camino snap (fondos rayados), que pegaba x FIJO. Barrido
ρ∈{0.75…0.95} × amp∈{6…10}: meseta — se conservan los defaults ρ=0.9/amp=6.

**Antes → después (estimador corregido, banco real, prosa larga de 6
párrafos ≈ 21 renglones, media±sd de seeds 42/7/101/13/77):**

| métrica | Escolar (snap) | Limpio (clásico) | estilo neutro (clásico) | humano |
|---|---|---|---|---|
| `margin_autocorr` | 0.100±0.200 → **0.652±0.137** ✅ | 0.327±0.136 → 0.326±0.149 | → 0.417±0.133 / 0.437±0.160 ✅ | > 0.40 en media |
| `margin_sigma` | 0.15 → **1.89 px** | 1.26 → 1.49 px | → 1.44–1.49 px | banda ≠ regla |

El camino snap era el margen "de regla" absoluto (σ=0.15 px) y ahora respira
como mano. En el camino clásico el mecanismo ya venía activo desde R3: con el
estimador corregido su "antes" real era ~0.33, y el ciclo lo deja igual en
Limpio (0.33±0.15, indistinguible de 0.40 dentro del error del estimador) y
en ≥0.40 con el estilo neutro. Tiempo de render: 3.5 s/página antes → 2.3–3.2
s/página después (sin costo medible; muy por debajo del techo 2.5× pre-R6).

### R14 · Ciclo C2.2 — sangría de primera línea de párrafo (perilla del ciclo)

Perilla: `para_indent_frac` (default 0.85·font_size; gauss truncada σ=0.35·μ
acotada a [0.45, 1.7]·μ por párrafo). Vive SOLO en el pegado del camino plano
(clásico, snap y render_text); la detección de estructura no se toca y la
prosa con líneas en blanco sigue cayendo al camino plano
(tests/test_writer_structure.py::test_prosa_con_lineas_vacias_no_dispara).

**Antes → después (banco real, prosa larga, 5 seeds):**

| métrica | Limpio | Escolar | objetivo |
|---|---|---|---|
| `indent_delta_mu` | −0.1 px → **33.2±5.6 px** | 0.8 → **36.5±5.3 px** | ≈ 0.85·44 = 37 px ✅ |
| `indent_delta_sigma` | 1.5 → **15.1 px** | 2.6 → **12.5 px** | variación humana acotada ✅ |
| `margin_autocorr` | 0.33 → 0.50±0.22 | 0.60 → 0.60±0.21 | se mantiene ✅ |
| `right_ragged_cv` | 0.15 → 0.18 | 0.17 → 0.19 | informativa, sana ✅ |

n_paragraphs 6/6 en todas las seeds (la detección no se confunde con la
sangría). Tiempo de render sin cambio (~3.1 s/página).

### R14 · Ciclo C2.3 — respiración inter-párrafo (perilla del ciclo)

Perilla: `para_breath_px` (default 4 px): desplazamiento vertical acotado
(tnorm σ=0.5·amp, ±amp) de la primera línea de cada párrafo, NO acumulativo,
SOLO camino clásico — en fondos rayados (snap) el texto sigue clavado a los
renglones reales (verificado: bytes idénticos con la perilla encendida y
apagada en Escolar). Mecanismo verificado a nivel de pegado (20 seeds, 40
draws: media 0.00, σ=3.74≈4 escalada, acotada, solo entre párrafos — la
primera línea del documento no respira). El CV de huecos de párrafo medido
por tinta NO lo resuelve (piso de ruido 0.19 por descendentes/jitter vs señal
±2 px finales: 0.189→0.194): el efecto es deliberadamente sutil, del orden
del jitter vertical humano, y queda documentado a nivel de mecanismo.

## R14 · C2.4 — golden horizontal + fix de sangría en export multipágina

Golden de estructura horizontal congelado y corrección de la sangría de
párrafo en el camino de export multipágina (`iter_pages` reinicia
`_begin_render` por trozo, así que la señal `_first_opens_paragraph` debe
propagarse entre páginas para que la sangría no se pierda en el corte).

## R15 — Tinta de pluma real: modulación en ESPACIO DE TRAZO

Salto del alpha binario del banco a textura de tinta procedural sin skeleton:
la orientación sale del gradiente del distance-transform suavizado y las
coordenadas a-lo-largo/cruzando el trazo se muestrean con `cv2.remap`. Perillas
(defaults verificados en `RenderOptions`):

| perilla | default | efecto |
|---|---|---|
| `ink_stroke_space` | `True` | activa toda la familia de modulación en espacio de trazo |
| `ink_boost` | `0.92` | ganancia global de tinta (R7 usaba 0.7) |
| `pen_skip_prob` | `0.01` | micro-skips en la cresta del distance-transform (R14 Track B) |
| `connector_prob` | `0.0` | uniones procedurales entre letras (alpha 110; a 150 tesseract fusiona, −4 pts OCR) |

Familia asociada (docstrings del código son la fuente): `ink_along_darkness`,
`ink_width_along`, `ink_streak_*`, `ink_pool_boost`, `ink_hue_by_density`,
`ink_paper_showthrough`.

**Rollback exacto a R7** (verificado byte-idéntico con seed fija, dimensión
'rollback' de la auditoría de merge): `ink_stroke_space=False, ink_boost=0.7,
pen_skip_prob=0`. Los defaults R14/R15 son opt-in: con las perillas apagadas la
salida es reproducible y determinista (misma seed → mismo PNG).

Regresión de legibilidad: `tools/eval_render/r14_eval.py` / `r15_eval.py`
(tesseract spa; usar difflib con `autojunk=False`). Baseline 83.8% vs
todo-ON 83.1%.

## R16 — Export a plotter: texto → trazos vectoriales SVG (pasos 1-2)

`core/inkcore/plotter/`: convierte el texto renderizado a trazos vectoriales
SVG a escala física 1:1 (mm), para plotters/lápiz robótico. Pasos 1-2 del
plan; línea de investigación abierta en `v5-dev`.
