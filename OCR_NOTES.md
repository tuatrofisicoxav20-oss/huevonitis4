# OCR_NOTES.md — Transcripción de foto manuscrita (Fase 0.5)

Backend nuevo `core/ocr/backends/trocr.py` (`TrOCRBackend`, registrado como
`"trocr"`). Modelo `microsoft/trocr-base-handwritten` (~400 MB, se descarga la
primera vez al cache `OCR_CACHE_DIR`). En CPU (sin GPU): carga ~1–2 min la
primera vez; luego ~1–3 s por línea.

## Pipeline
1. `imread_oriented` + `orient_by_content` — orientación por CONTENIDO (las fotos
   de WhatsApp pierden el EXIF; se reusa lo del extractor, no se reinventa).
2. `ImagePreprocessor.deskew` + `normalize_illumination` + `enhance_contrast` —
   endereza y aplana sombras/contraste de foto de celular.
3. Segmentación en líneas por proyección horizontal de tinta (TrOCR rinde por
   línea, no por página).
4. **Recorte horizontal** de cada línea a su extensión de tinta — clave: el
   espacio en blanco sobrante hacía que TrOCR ALUCINARA (inventaba números al
   final). Recortado, desaparece.
5. TrOCR por línea (num_beams=2) → texto + confianza por línea
   (`exp(sequences_scores)`), para que la UI de revisión resalte lo dudoso.

## Resultado honesto (medido 2026-06-07)

**Prosa** (caso de uso real). Imagen de prueba: un párrafo escrito con el banco
del usuario, rotado −1.5° para simular foto.
- GT:   `la casa de mi abuela es muy bonita y tiene un jardin con flores`
- PRED: `la casa de mi abueld es mux bonita y tiene un jardin con flores`
- **Word similarity ≈ 0.86**; ~9/12 palabras exactas, el resto cercanas
  (`abueld`→abuela, `mux`→muy) + capitalización ocasional.
- Confianza por línea: 0.82 / 0.84.
- **Antes del recorte horizontal**: 0.63 y números alucinados (`1882 1953 …`).

**Foto real disponible**: las de `muestras/` son **abecedarios de molde** (hojas
para el banco), no prosa. TrOCR sobre letras sueltas/espaciadas alucina
(`"# not be able for his influence ."`, **confianza 0.23**). La baja confianza
lo marca correctamente como dudoso. Para validar end-to-end sobre una FOTO real
de apuntes en prosa hace falta que el usuario aporte una (las muestras actuales
no sirven para eso).

## Conclusión
TrOCR cumple el rol pedido: **asistente que produce un borrador corregible**, no
transcripción perfecta (decisión explícita del master prompt). La mayoría de las
palabras de prosa son reconocibles y la confianza por línea guía la revisión
humana (Fase 0.6). NO se intenta OCR perfecto.

## Pendiente / v2
- Probar con una foto real de un párrafo manuscrito (no abecedario).
- Modelo `small` (más rápido) vs `large` (más preciso) según RAM/tiempo: ya es
  configurable por `config.TROCR_MODEL`.
- Corrección ortográfica post-OCR (diccionario español) para subir el borrador.
