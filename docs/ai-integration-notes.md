# Notas de integración de IA — InkCore

## Modelos de IA encontrados en el sistema (2026-05-20)

- `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/faster-whisper-base/model.bin`
  → Whisper (ASR audio), no aplica a glifos.
- `~/Documentos/chapi_assistant/es_MX-ald-medium.onnx`
  → Piper TTS (síntesis de voz), no aplica.
- `~/hand-gesture-recognition-mediapipe/model/keypoint_classifier/keypoint_classifier.tflite`
  → Clasificador de gestos de mano (MediaPipe). Podría adaptarse a reconocimiento de
  caracteres manuscritos si se reentrena con imágenes de glifos (21 puntos clave →
  vector de características por glifo).
- `onnxruntime 1.25.1` y `opencv 4.11.0` instalados en el entorno.

## Cómo integrar un clasificador real

Para reemplazar `FallbackGlyphClassifier` con un modelo ONNX real:

1. Entrenar un modelo CNN simple (ResNet18 pequeño) sobre imágenes de glifos
   del banco (`~/.local/share/huevonitis4/tipografia/`). Exportar a ONNX con
   `torch.onnx.export()`.

2. En `__init__`:
   ```python
   import onnxruntime as ort
   self._session = ort.InferenceSession("glyph_classifier.onnx")
   self._labels = [...]  # lista de chars del modelo
   ```

3. En `predict()`:
   ```python
   img_arr = np.array(img.resize((64, 64)).convert("L"), dtype=np.float32)
   img_arr = (img_arr / 255.0)[np.newaxis, np.newaxis, ...]
   logits = self._session.run(None, {"input": img_arr})[0]
   predicted_char = self._labels[np.argmax(logits)]
   ```

4. Para clasificación de calidad con el TFLite de MediaPipe:
   ```python
   import tflite_runtime.interpreter as tflite
   interpreter = tflite.Interpreter(model_path=".../keypoint_classifier.tflite")
   # Extraer 21 keypoints del glifo vía distancia transform y usarlos
   # como entrada al clasificador de gestos (reentrenado para chars).
   ```

## Paquetes instalados relevantes

- `onnxruntime 1.25.1` → listo para inferencia con modelos ONNX
- `opencv 4.11.0` → listo para preprocesamiento de imágenes
