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

## R17 — Presión por glifo + física de tinta reforzada (juez visual + jurado)

Metodología nueva: **juez de visión en el loop**. Se renderiza, se simula la
foto de tarea (`photo_export`), y un **jurado adversarial de 5 modelos de
visión** (workflow) puntúa "manuscrito vs impreso/generado" y lista los tells;
cada tell se ataca con UNA perilla por ciclo, midiendo OCR canónico
(`r15_eval`, tesseract spa, media de 3 seeds) y el jurado antes/después.

**Referencia real anclada:** las plantillas del usuario (`Image to PDF *.pdf`)
y su alfabeto manuscrito (`muestras `) confirman que su letra es de estilo
BLOQUE: la `o` minúscula es un círculo, la `f` una forma tipo `F`, la `l` un
palito vertical, la `s` una curva tipo `S`. El "mixed-case" que el jurado tacha
de artefacto **es la letra auténtica del usuario** — el banco es fiel y NO se
altera (cambiarla rompería el propósito de la app). Los delatores reales
atacables son sintéticos: tinta plana y clones perceptuales.

Perilla nueva `glyph_pressure_jitter` (default **0.22**): jitter I.I.D. de
presión→oscuridad POR glifo (gauss truncada ±2.2σ) sumado al latente OU lento
de R14. La letra real varía RÁPIDO (una `l` pálida junto a una `k` densa); el
OU solo daba variación lenta (~3 renglones). RNG sólo si >0 (byte-idéntico con
0). Lever de realismo #1 confirmado por el jurado.

Defaults de tinta subidos (R15→R17, jurado: "trazo plano, sin física de
bolígrafo"): `ink_along_darkness` 0.18→0.28, `ink_width_along` 0.10→0.16,
`ink_streak_strength` 0.15→0.20, `ink_pool_boost` 0.15→0.28,
`ink_hue_by_density` 0.10→0.12, `pen_skip_prob` 0.01→0.03. Sólo tocan
RGB/textura-de-alpha, no la geometría.

**Gate canónico r15_eval:** 81.9% vs baseline 83.3% → Δ **1.4 pts** (≤3, PASA).
⚠ **Gotcha medido:** un harness casero (psm 6, prosa propia) daba −0.7 pt e
inducía a error; el gate oficial (seed 1234) daba −5 pt con los defaults
iniciales (gpj 0.30 + warp 0.10). Se recalibró a gpj 0.22 y warp de vuelta a
0.08 (el clone-breaking geométrico cuesta OCR y apenas ayuda: los clones se
perciben porque las variantes del banco son muy parecidas entre sí, no por
reuso — 73/74 fuentes únicas en 74 selecciones). **Validar SIEMPRE con
`r15_eval`/`r14_eval` en varios seeds, no con métricas caseras.**

**Aislamiento de tests:** las nuevas fuentes de variación se apagan en los
controles negativos (`test_anti_sello_bilateral`), en los tests que aíslan el
paso de borde (`test_edge_no_consume_rng_del_layout`: la presión mueve el bbox
de tinta y cruza celdas del ruido de `apply_paper` — misma dependencia de datos
que `hand_energy`) y en `test_connector_agrega_enlace` (`pen_skip` quita tinta,
la presión cambia el alpha). Suite: 456 passed.

**Jurado (foto de tarea, 5 votos):** score medio ~16→~22/100. El techo lo
imponen mixed-case (inherente) y clones (OCR-limitados). Lever futuro
documentado: bolitas de tinta pen-down/pen-up (requiere detección fiable de
extremos de trazo — esqueleto; se omitió por riesgo de regresión OCR/visual).
Rollback exacto a R15: `glyph_pressure_jitter=0.0` + los 6 defaults de tinta
previos (0.18/0.10/0.15/0.15/0.10/0.01).

### R17b — bolitas de tinta pen-down/pen-up (extremos de trazo)

Se implementó el lever que R17 dejó pendiente por riesgo. `apply_ink_blobs`
(`renderer_ink.py`) detecta los EXTREMOS del trazo con el esqueleto
(`skimage.skeletonize` → píxeles con 1 vecino) y SUMA un blob gaussiano al alpha
en 1-2 extremos por glifo: el charco redondeado que deja la punta del bolígrafo
al apoyarse. Perilla `ink_blob_strength` (default **0.30**, clamp 0..0.6).

- **Sólo AGREGA alpha** (`np.clip` suma) → nunca adelgaza ni corta el trazo:
  cero riesgo de romper legibilidad. De hecho el OCR canónico MEJORA levemente
  (más tinta): r15_eval **82.4% vs 83.5% baseline, Δ1.1 pts**.
- RNG PROPIO sembrado del contenido (patrón de `apply_pen_skips`) → byte-idéntico
  con `ink_blob_strength=0` (opt-in real). Corre DESPUÉS del borde R12 (el charco
  debe quedar nítido).
- Clamps: no en glifos diminutos (min dim < 0.16·fs), radio ≤ 0.085·fs anclado
  al semiancho local (dt). Costo de render +18% (1.54→1.82 s/pág; el esqueleto
  por glifo es barato).
- **Aislamiento:** las bolitas engordan el bbox de tinta → se apagan en los
  goldens de geometría (`test_golden_metricas_linea_base`,
  `test_golden_estructura_horizontal`: mismo motivo que `ink_texture_v2=False`)
  y en los controles de borde/conector/sello. Suite: **456 passed**.
- **Verificación visual:** los charcos son visibles al zoom (extremos de `l`,
  `t`, finales de palabra) — leen como depósito de bolígrafo. En la foto de
  tarea comprimida se atenúan (el jurado abstracto no los registra fuerte),
  pero NO introducen artefactos. El jurado sigue en ~15-22 (techo de mixed-case
  + clones, inherentes). Rollback: `ink_blob_strength=0.0`.

### R17c — tinta "viva": deriva de presión por página + textura de trazo

Objetivo directo del usuario ("que no se vea IMPRESO"). El tell de impresora es
tinta UNIFORME a lo largo de toda la página (el tóner es parejo); una pluma real
carga/descarga y sangra en la fibra. Se subieron los defaults:

| perilla | R17b → R17c | efecto anti-impreso |
|---|---|---|
| `hand_energy_sigma` | 0.6 → 0.95 | deriva LENTA de presión visible por párrafo |
| `pressure_darkness_coupling` | 0.15 → 0.30 | esa deriva oscurece/aclara zonas |
| `session_shift_prob` | 0.02 → 0.05 | "re-carga de tinta" (saltos de energía) |
| `glyph_pressure_jitter` | 0.22 → 0.26 | variación rápida por glifo |
| `ink_along_darkness` | 0.28 → 0.38 | densidad variable a lo largo del trazo |
| `ink_streak_strength` | 0.20 → 0.28 | textura "riel" de bolígrafo |
| `ink_pool_boost` | 0.28 → 0.34 | apozamiento en cruces/vueltas |
| `ink_bleed` | 0.4 → 0.5 | sangrado en la fibra del papel |
| `ink_edge_irregularity` | 0.5 → 0.72 | borde irregular (no vectorial) |
| `ink_paper_showthrough` | 0.06 → 0.11 | tinta semi-transparente, no opaca |

**Gate canónico r15_eval: 81.8% vs 83.4% (Δ1.6, PASA).** Combo verificado en
media de 3 seeds (82.0%, todos estables). Aislamiento: `test_presion_oscurece_el_trazo`
apaga el stroke-space (el shading enmascaraba la señal pressure→color) y el golden
de geometría apaga `ink_bleed`/`ink_stroke_space` (el sangrado engorda las cajas
medidas). Suite: **456 passed**.

**CONCLUSIÓN tras 6 rondas de jurado (30 votos):** el score forense "¿manuscrito?"
se estanca en ~15-28 PASE LO QUE PASE con tinta/papel. Los 3 delatores dominantes
son SIEMPRE los mismos y los tres son la LETRA AUTÉNTICA del usuario: (1) estilo
bloque (o=círculo, f=forma-F → lee como "mayúsculas a media palabra"); (2) `s`
muy consistente (41 variantes casi iguales → lee como "clon"); (3) `l` de palito
(lee como `i`/`!`). Ni tinta ni papel los mueven. El clone-breaking geométrico
(warp/rotación) es veneno de OCR (tumba seeds a 73%). **El único lever restante es
MODIFICAR las formas de letra** (l distinta, normalizar caja, morphing de variantes)
— decisión del usuario, cambia SU letra. Rollback R17c: los 10 valores previos de
la tabla.

### R17d — asta ascendente (arregla l≡i y el ritmo "versalita")

La letra del usuario es de altura UNIFORME: `l` (0.45 em) ≡ `i` (0.47 em) → se
lee `ios` por `los`. Y la ausencia total de astas/colas hace que TODO lea como
versalita/bloque. `ascender_boost` (default 0.45) estira SOLO en vertical
(`target_w` se fija con el ratio normal antes de crecer `target_h`; el baseline
escala con la altura → el asta crece hacia ARRIBA) las letras de `ascender_chars`
(default `"ldbhk"`). **'t' se EXCLUYE**: la t-cruz del usuario estirada se lee
como `T` (empeora el look mayúscula — confirmado por el jurado). Mejora la
legibilidad: r15_eval subió de ~81.8% a **84.2% (Δ1.2, PASA)** — distinguir l/i
ayuda a tesseract. Aislamiento: los goldens de geometría y
`test_e10_baselines_anclados_a_renglones` (las astas llenan el hueco
inter-renglón y el clustering de filas fusiona líneas) apagan `ascender_boost`.

### R17e — jitter de proporción por instancia (perilla opt-in, DEFAULT 0)

`glyph_aspect_jitter` escala ancho/alto independientes por instancia para romper
"clones" sin distorsionar la topología (a diferencia del warp elástico). **Se
dejó en 0**: el jurado NO lo acredita —los clones que percibe vienen de que las
41 variantes de `s`/`o` del usuario son casi iguales entre sí, no del aspecto— y
cuesta ~3 pts de OCR. Queda disponible para experimentar.

### VEREDICTO FINAL (7 rondas de jurado, 35 votos)

Lo que se arregló y mejora de verdad: tinta viva (R17c), física de bolígrafo +
charcos (R17/b), y asta ascendente (R17d, arregla l/i + ritmo). Lo IRREDUCIBLE
sin cambiar las formas de letra del usuario: (1) `o`/`f`/`s`/`c` con forma de
BLOQUE → un lector ve "mayúsculas a media palabra"; (2) `s` súper consistente →
"clones". El banco NO tiene variantes de minúscula de esas letras (todas son
círculos/curvas-S/F-bloque): así escribe el usuario. Levers cerrados por OCR:
warp/rotación fuerte (tumba seeds a 73%), aspect jitter (−3pt), jitter de ritmo
(−3pt). Papel de cuaderno (Escolar): no mueve al jurado, añade tell "flota sobre
renglones"; el usuario eligió hoja blanca. **Acentos**: el banco SÍ los tiene
(á/é/í/ó/ú×12, ñ×40) — texto sin tildes lee como ASCII; recomendación de uso:
escribir con tildes.

## R18 — FATIGA en textos largos + variación de color por documento

Dos ejes de variación de DOCUMENTO (el latente e(t) de R14 era estacionario por
página; esto añade tendencia a lo largo del documento y entre documentos).

**Fatiga acumulativa** (`fatigue_strength` default 0.5, `fatigue_onset_lines` 32):
la letra se degrada conforme avanza el documento — crece y se afloja, la
inclinación deriva hacia UN lado, la línea base se hunde, la presión se vuelve
errática. Nivel = `strength·(1−exp(−línea/onset))`; contador de renglón GLOBAL
(persiste entre páginas de un `render_pages`; `_doc_line_start` da continuidad en
`iter_pages`). Acopla a size_drift (+12%·fat), rotación por glifo (drift +
temblor), presión (más errática) y baseline (hunde ≤9 px). **Umbral 0.10**: por
debajo (textos <~7 renglones) NO consume RNG → byte-idéntico a fatiga-off,
protege el gate y no perturba la selección de variantes. Verificado visualmente:
en una página larga los primeros renglones son limpios y los últimos claramente
más grandes/desalineados.

**Color por documento** (`ink_color_doc_var` default 0.5): desplaza tono/valor
del `ink_color` una vez por render con un RNG DERIVADO del seed (NO toca el stream
de `_rng` → geometría/selección idénticas, sólo color). Cada tarea parece escrita
con un boli un pelo distinto. Guardado en `self._doc_ink_color` (NO muta options:
reusar el objeto da el mismo color, no doble shift).

**Gate r15_eval: Δ0.7 pts (PASA).** Aislamiento: goldens de geometría,
`test_e10_baselines`, `test_calibration` (round-trip de espaciado) apagan
`fatigue_strength`/`ascender_boost`. Suite 456. Rollback: `fatigue_strength=0`,
`ink_color_doc_var=0`.

**Nota de entorno (2026-07-08):** `opencv-python 4.5.5.64` (numpy-1) shadueaba a
`opencv-python-headless` y rompía `import cv2` bajo numpy 2.3.5 (39 tests OCR).
Resuelto reinstalando opencv (→ 4.11.0, compat numpy 2). No relacionado con el
render.
