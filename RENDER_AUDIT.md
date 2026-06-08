# RENDER_AUDIT.md — Auditoría del renderer (Fase 0)

Punto de partida ANTES de tocar nada, para no reescribir lo que ya funciona.
Medido el 2026-06-07 sobre el banco real (perfil `default`, 659 glifos).

## Dónde vive el renderer

- `core/inkcore/renderer.py` — `HandwritingRenderer` (+ `RenderOptions`).
  - `render_text()` — texto → imagen RGB (ruta principal; usa `render_pages`
    si >30 líneas).
  - `render_pages()` — divide en páginas de alto fijo (lista de imágenes RGB).
  - `render_transparent()` — variante sobre fondo transparente (replicador).
  - `_render_line()` — el corazón: coloca los glifos de un renglón.
  - `_soft_wrap_text()` — word-wrap por palabra (estimación por ancho medio).
- `core/inkcore/renderer_glyph.py` — `GlyphLoadMixin._load_glyph()`: carga,
  recolorea, recorta al bbox, escala POR CLASE tipográfica, rota, inclina y
  ajusta alpha (tinta).
- `core/inkcore/renderer_backgrounds.py` — fondos (libreta/cuadrícula/margen)
  y `STYLE_PRESETS`.
- Selección de glifo: `core/inkcore/bank.py` → `GlyphBank.get_best_glyph()`.

## Cómo funciona hoy (los 5 ejes)

### 1. Selección de glifo por carácter
`get_best_glyph(char, variation=True)` (lo que usa el renderer):
- Filtra candidatos por tier: usa **Gold** si hay; si no, Silver; si no, todos.
- Con `variation=True` → `random.choice` uniforme dentro de ese grupo.
- **NO** hay memoria de las últimas N apariciones → puede repetir el MISMO
  glifo dos veces seguidas. **NO** hay muestreo ponderado por tier (Gold/Silver
  no rotan juntos; si hay Gold, Silver nunca entra). **NO** hay `seed`
  reproducible. → Esto es lo que ataca la **Fase 1**.

### 2. Posición X (espaciado)
- `x_cursor` avanza por `glyph.width` (ancho real del bbox, no fijo) +
  `spacing_gap` base (`font_size*0.08`, mín 2px).
- `kerning_jitter` (default 0.5) varía el hueco ±50% al azar por par.
- Espacio de palabra: `max(4, font_size*0.4)`.
- → La **Fase 3** (espaciado variable + word-wrap) ya está implementada.

### 3. Posición Y (baseline)
- Lienzo de renglón alto `font_size*2.5`; baseline en `int(h*0.72)`.
- `baseline_drift` (default 1.2): random walk acotado y suavizado (no ruido
  blanco) → la línea ondula levemente.
- Baseline POR CLASE: x-height asienta en el baseline; ascendentes suben;
  descendentes meten ~31% del glifo bajo el baseline.
- Jitter vertical por glifo: ±2px (acotado).
- → La **Fase 2** (jitter de baseline con correlación) ya está implementada.

### 4. Rotación / escala / inclinación por glifo
- `rotation_range` (default 4°): rotación al azar por glifo, `expand=True`,
  resample BICUBIC, preservando alpha (sin halos — BUG-18 ya resuelto).
- `size_variation` (default 0.12): escala ±12% por glifo, multiplicando sobre
  la altura de clase.
- `slant_deg`: shear opcional (cursiva reclinada). v1 = 0.
- → El grueso de la **Fase 2** (rotación + escala) ya está.

### 5. Tinta y papel
- `_recolor_ink`: repinta la forma con `ink_color` (#1A1A2E) preservando alpha.
- `ink_boost` (gamma<1 sobre alpha): trazo sólido tipo bolígrafo.
- `ink_alpha_min/max` (0.86–1.0): variación de "presión" por glifo.
- Fondos: libreta (rayas + margen rojo), cuadrícula, hoja blanca. Las rayas se
  dibujan ALINEADAS al baseline real del texto (las letras se apoyan en la raya).
- → La **Fase 4** (textura de papel + variación de tinta) ya está implementada.

### Saltos de línea / página
- `_soft_wrap_text` reparte en renglones por palabra (no corta palabras salvo
  que una palabra sola exceda el ancho).
- `_render_line` además protege: si una palabra no entra, la pasa entera al
  renglón siguiente.
- `render_pages` corta en páginas por `lines_per_page = usable_height //
  line_height_px`. **Genera la lista completa de páginas en memoria** → la
  **Fase 5** debe pasar a escribir-y-liberar para 36+ páginas.

## Página baseline

`baseline_render.png` (regenerable con `tmp/phase0_audit.py`). Texto:
> "El veloz murcielago hindu comia feliz cardillo y kiwi. La ciguena tocaba el
> saxofon detras del palenque de paja. Nono 123."

Observaciones visuales:
- Letras asentadas sobre las rayas, tinta tipo bolígrafo, renglón ondula leve.
- **Dígitos `123`**: el banco no tiene dígitos → caen al fallback (fuente
  LiberationMono) y se ven de IMPRENTA, desentonando. Pendiente (capturar
  dígitos o fallback manuscrito).
- Acentos (í, ü, é) y Ñ/ñ: dependen de cobertura del banco; los que faltan caen
  al fallback de imprenta.

## Mediciones (página única, 1240×400)

| Métrica | Valor |
|---|---|
| Tiempo de render | **363 ms** |
| Pico de RAM (tracemalloc) | **1.7 MB** |
| Repeticiones consecutivas del mismo glifo | **5** (objetivo Fase 1: 0) |

Variantes distintas usadas por carácter (apariciones / distintas):

| char | aprir. | distintas | nota |
|---|---|---|---|
| a | 12 | 4 | vocal repetida ✔ (≥3) |
| e | 11 | 8 | vocal repetida ✔ |
| i | 8 | 7 | vocal repetida ✔ |
| o | 9 | 6 | vocal repetida ✔ |
| l | 10 | 8 | ✔ |

**El gate de la Fase 1 (≥3 variantes para vocales con ≥5 apariciones) YA se
cumple** gracias al `random.choice`. Lo que falta de la Fase 1 es solo evitar
las **repeticiones consecutivas** (5 medidas) y agregar muestreo ponderado +
`seed` reproducible.

## Estado real de cada fase (honesto)

| Fase | Estado | Qué falta |
|---|---|---|
| 0 baseline | **este doc** | — |
| 0.5 OCR foto→texto (TrOCR) | por construir el flujo | hay deps/config TrOCR; falta pipeline foto→líneas→texto+confianza |
| 0.6 UI revisión foto/texto | por construir | — |
| 1 selector variantes | **casi completo** | no-repetir-últimas-N, muestreo ponderado, seed |
| 2 jitter baseline/rot/escala | **completo** | (verificar sin halos) |
| 3 espaciado variable + wrap | **completo** | — |
| 4 textura papel + tinta | **completo** | margen rojo ya; grano de papel opcional |
| 5 PDF 36+ pág RAM constante | parcial | `render_pages` acumula en RAM; falta streaming a disco |
| 6 diagramas a mano | parcial | existe `concept_map.py` (árbol a mano); faltan primitivas (flecha/caja/círculo/llave) y mapa mental |
| 7 integración UI del flujo | parcial | falta cablear foto→OCR→revisión→preview→PDF + sliders RENDER_PARAMS |

## Verificación de gates (Fases 1–4)

Medido tras implementar la Fase 1 (selector) sobre el banco real:

| Gate | Criterio | Medido | ¿Pasa? |
|---|---|---|---|
| 1 | ≥3 variantes por vocal con ≥5 apariciones | a:6 e:10 i:7 o:8 | ✅ |
| 1 | repeticiones consecutivas del mismo glifo | 0 (baseline: 5) | ✅ |
| 1 | seed reproducible | seed=42 idéntico 2×; ≠ seed=7 | ✅ |
| 2 | baseline ondula | std base por columna = 5.05 px (>0) | ✅ |
| 2 | rotación SIN halos | RGB donde hay tinta = [11,11,20] (color tinta, no gris/negro) | ✅ |
| 3 | espaciado variable | std de separaciones = 9.84 px (>0) | ✅ |
| 4 | texto se apoya en las rayas | rayas alineadas al baseline real + snap a libreta | ✅ (visual) |

## Conclusión Fase 0

El **escritor (Fases 1–4) está esencialmente hecho** y medido bien. El trabajo
real del master prompt es: **OCR + UI de revisión (0.5/0.6)**, **streaming de PDF
(5)**, **primitivas de diagrama (6)** e **integración de UI (7)**, más pulir el
selector (1). No hay que reescribir el renderer.
