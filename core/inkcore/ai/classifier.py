"""
Clasificador de glifos para Huevonitis 4.

FallbackGlyphClassifier: clasificador basado en reglas (sin ML).
Usa características de imagen y heurísticas de nombre de archivo.

─── Modelos de IA encontrados en el sistema (2026-05-20) ─────────────────
• /home/exitili/.cache/huggingface/hub/models--Systran--faster-whisper-small/
  faster-whisper-base/model.bin  →  Whisper (ASR audio), no aplica a glifos.
• /home/exitili/Documentos/chapi_assistant/es_MX-ald-medium.onnx  →  Piper TTS
  (síntesis de voz), no aplica.
• /home/exitili/hand-gesture-recognition-mediapipe/model/keypoint_classifier/
  keypoint_classifier.tflite  →  Clasificador de gestos de mano (MediaPipe).
  Podría adaptarse a reconocimiento de caracteres manuscritos si se reentrena
  con imágenes de glifos (21 puntos clave → vector de características por glifo).
• onnxruntime 1.25.1 y opencv 4.11.0 instalados en el entorno.

─── Cómo integrar un clasificador real ───────────────────────────────────
Para reemplazar FallbackGlyphClassifier con un modelo ONNX real:

    1. Entrenar un modelo CNN simple (ResNet18 pequeño) sobre imágenes de glifos
       del banco (~/tipografia/). Exportar a ONNX con torch.onnx.export().

    2. En __init__:
           import onnxruntime as ort
           self._session = ort.InferenceSession("glyph_classifier.onnx")
           self._labels = [...]  # lista de chars del modelo

    3. En predict():
           img_arr = np.array(img.resize((64, 64)).convert("L"), dtype=np.float32)
           img_arr = (img_arr / 255.0)[np.newaxis, np.newaxis, ...]
           logits = self._session.run(None, {"input": img_arr})[0]
           predicted_char = self._labels[np.argmax(logits)]

    4. Para clasificación de calidad con el TFLite de MediaPipe:
           import tflite_runtime.interpreter as tflite
           interpreter = tflite.Interpreter(
               model_path=".../keypoint_classifier.tflite"
           )
           # Extraer 21 keypoints del glifo vía distancia transform y usarlos
           # como entrada al clasificador de gestos (reentrenado para chars).

─── Paquetes instalados relevantes ───────────────────────────────────────
• onnxruntime 1.25.1  →  listo para inferencia con modelos ONNX
• opencv 4.11.0       →  listo para preprocesamiento de imágenes
"""
import logging
from core.inkcore.ai.contracts import GlyphPrediction
from core.inkcore.ai.features import (
    extract_image_features,
    infer_char_from_path,
    confidence_adjustment_from_features,
)

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class FallbackGlyphClassifier:
    """Rule-based glyph classifier using image features and filename heuristics.

    Used when no ML backend is available. Combines quality score,
    alignment score (from DP), and image feature penalties.
    """

    def predict(
        self,
        img: "Image.Image",
        assigned_char: str = "",
        path: str = "",
        quality_score: float = 0.0,
        alignment_score: float | None = None,
    ) -> GlyphPrediction:
        if not _PIL_OK:
            return GlyphPrediction(
                char=assigned_char, confidence=0.5,
                quality_score=quality_score, needs_review=True,
            )
        features = extract_image_features(img)
        char = assigned_char or infer_char_from_path(path)

        if alignment_score is not None:
            base_conf = 0.25 + 0.38 * quality_score + 0.37 * max(0.0, min(1.0, alignment_score))
        else:
            base_conf = 0.42 + 0.45 * quality_score

        adj = confidence_adjustment_from_features(features)
        confidence = max(0.05, min(0.98, base_conf + adj))

        flags = list(features.warnings)
        if confidence < 0.68:
            flags.append("low_confidence")
        if quality_score < 0.70:
            flags.append("low_quality")

        # Bug fix #6: only trigger needs_review for genuinely serious signals.
        # Minor warnings (very_high_ink, border touch) must not override a
        # Gold-quality glyph (quality >= 0.75, confidence >= 0.68).
        SERIOUS_WARNINGS = {"very_low_ink", "too_small", "zero_size"}
        has_serious_warning = bool(SERIOUS_WARNINGS & set(features.warnings))
        needs_review = (
            confidence < 0.68
            or quality_score < 0.46
            or has_serious_warning
        )

        return GlyphPrediction(
            char=char,
            confidence=round(confidence, 3),
            quality_score=round(quality_score, 3),
            needs_review=needs_review,
            flags=flags,
        )
