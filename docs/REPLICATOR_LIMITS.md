# Replicador de apuntes — Limitaciones (v4.2 MVP)

El tab 🔁 Reproducir permite cargar un apunte ajeno y regenerarlo con la
letra del perfil activo. Este es un **MVP** con alcance acotado.

## Lo que SÍ hace

- ✅ **Texto manuscrito impreso/legible** — detecta líneas con tesseract
  (PSM 6, `--oem 3`, idiomas `spa+eng`) y las re-escribe con tu letra.
- ✅ **Recuadros simples** — contornos cuadrangulares grandes con
  `cv2.findContours` + `approxPolyDP`. Se re-trazan con jitter de ±2px
  para que se vean manuscritos.
- ✅ **Posición y tamaño aproximados** — cada bloque se ubica en su
  posición original del apunte fuente.
- ✅ **Slider de fidelidad 0–100** — 0 = todo replicado, 100 = copia
  exacta del original. Intermedios hacen blend lineal.
- ✅ **Toggles por bloque** — el usuario puede desmarcar bloques
  específicos para excluirlos.

## Lo que NO hace (por diseño en MVP)

- ⚠ **Fórmulas matemáticas** — se quedan como bitmap. No hay OCR
  matemático integrado (Mathpix / pix2tex no son dependencias). Si tu
  apunte tiene mucha matemática estructurada, el resultado va a parecer
  texto "raro" porque tesseract no entiende `∑`, `∫`, fracciones, etc.
- ⚠ **Dibujos / diagramas / flechas** — no se re-trazan en MVP. Se
  preservan como bitmap copiando del original cuando fidelity > 0.
- ⚠ **Tablas** — solo se detectan rectángulos individuales, no la
  estructura de filas/columnas. Si tu apunte tiene una tabla, las celdas
  pueden detectarse como recuadros sueltos.
- ⚠ **Color** — el MVP renderiza en blanco y negro. Si el original tiene
  resaltadores o colores, se pierden.
- ⚠ **Páginas múltiples / PDFs** — el MVP procesa una sola imagen por
  vez. Para PDFs hay que extraer cada página y procesarla.
- ⚠ **Layouts complejos** — multi-columna, márgenes con anotaciones,
  cuadros de texto inclinados → tesseract falla y el bloque queda mal
  ubicado.

## Mejoras planeadas para v4.3+

- Detector de líneas/flechas con `HoughLinesP` re-trazadas a mano.
- Reconocimiento básico de tablas con grid de líneas H+V.
- Soporte multi-página para PDFs.
- Renderizado en color preservando highlights.

## Cómo probarlo

1. Asegúrate de tener glifos en el perfil activo (al menos a-z).
2. Tab 🔁 Reproducir → Elegir imagen.
3. Pulsa Analizar imagen → ver los bloques detectados a la derecha.
4. Desmarca los que no quieras replicar.
5. Pulsa Re-renderizar con mi letra.
6. Ajusta el slider de fidelidad si quieres más bitmap original.
7. Pulsa Exportar resultado para guardar PNG/PDF.
