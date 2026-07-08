# SPIKE_TINTAS — F3b (H5, bloque CODE) · Veredicto: **GO**

Mini-spike de recoloreo de tintas (azul / rojo / verde) sobre glifos REALES
del banco. **No integra nada**: script aislado `tools/spike_tintas.py` +
hojas comparativas en `muestras /tintas_spike/`. Medido el 02-jul-2026 sobre
el perfil `default` (1,174 glifos).

## Qué se probó

1. **Recoloreo por glifo con rampa de densidad** (`recolor_rampa`): densidad
   derivada del alpha (RGB del banco es blanco plano), mapeada a la rampa
   claro→oscuro del color destino; **alpha intacto** (verificado byte a byte:
   `True`). Hojas: `hoja_comparativa_200pct.png` / `_400pct.png`
   (original plano / azul / rojo / verde × 5 glifos: a e m q t).
2. **Pipeline real con `ink_color`** (ya es perilla existente — cero
   integración): la palabra "la tinta viva" renderizada por `render_pages`
   con R11 (textura intra-trazo) y R12 (borde) activos, en las tres tintas.
   Hojas: `pipeline_real_200pct.png` / `_400pct.png`.

## Hallazgo clave (corrige la premisa del spike)

El alpha de los glifos del banco es **casi binario**: 0 (fondo) o 255 (tinta
sólida), con solo una banda fina de antialiasing (~29% de los píxeles de
tinta del glifo medido, todos en 1–127; ninguno en 128–254). **En el PNG del
banco no hay textura de densidad que conservar** — la textura de tinta se
sintetiza al renderizar (`ink_boost` + R11 densidad-en-color + R12 borde).
Por eso la rampa por glifo solo modula el borde de antialiasing (std de valor
dentro de tinta: 23.5 vs 0.0 del recoloreo plano actual): correcta, pero de
efecto sutil.

La consecuencia es favorable: **el pipeline actual ya separa color de
forma** (tinte plano por reemplazo en `_recolor_ink` + composición multiply
en `apply_paper` + densidad modelada en el COLOR desde R11), y esos pases son
**agnósticos al tono**. La hoja del pipeline real lo confirma: azul, rojo y
verde salen con carga variable a lo largo del trazo y apozamiento en cruces,
idénticos en carácter al azul-negro por default.

## Veredicto: GO — integrable en ciclo posterior

- **Dónde colgarlo**: de los bloques que `writer_structure` ya distingue
  (`heading` / `numbered` / `bullet` / `paragraph`). `_build_blocklines` ya
  hace `replace(options, font_size=fs)` por bloque
  (`core/inkcore/writer_structure.py:259`); añadir ahí
  `ink_color=<tinta del tipo de bloque>` es el punto natural (p. ej. títulos
  en rojo, cuerpo en azul, como un apunte escolar real).
- **Costo estimado**: perilla(s) nuevas en RenderOptions (mapa
  tipo-de-bloque→color) + 1 línea en `_build_blocklines` + tests. Sin tocar
  banco, extracción ni métricas.
- **Precauciones para la integración** (no bloquean el GO):
  1. `jitter_ink_color` (micro-color por glifo) consume del RNG del render:
     el color por bloque no debe cambiar CUÁNTAS veces se tira del RNG o se
     rompe la reproducibilidad por seed (mismo cuidado que R12 con
     `edge_rng`).
  2. `apply_style` puede pisar `ink_color` (el preset Bolígrafo lo hace):
     definir el orden preset → color-por-bloque explícitamente.
  3. Glifos legacy opacos (alpha plano, rama `extrema(A)<12` de
     `_recolor_ink`) ya tienen su fallback por luminancia — el color por
     bloque lo hereda gratis; la rampa por glifo del spike NO es necesaria
     para integrar tintas.
