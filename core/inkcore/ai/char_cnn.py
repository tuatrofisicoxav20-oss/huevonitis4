"""Clasificador de caracteres manuscritos (CNN EMNIST) — inferencia offline.

Esto NO reemplaza el texto de referencia: el usuario igual escribe qué letras
son. Su rol es ser el JUEZ de los cortes: ante la línea de un abecedario, el
extractor parte por posición y a veces el corte cae desplazado; este clasificador
puntúa cada recorte candidato con P(letra_esperada), y el alineador elige los
cortes que maximizan esa probabilidad. Es la técnica recomendada en la literatura
para caracteres que se tocan (over-segmentación + selección guiada por
reconocimiento), no un OCR de línea (esos no recortan glifos limpios).

Carga perezosa y degradación elegante: si falta torch o el modelo no está, todo
queda `available=False` y el extractor sigue con su pipeline clásico.

El modelo se entrena con tools/train_char_cnn.py (EMNIST 'letters', 26 clases
a-z). La ñ no existe en EMNIST: para ñ el score cae a None y el caller usa su
heurística previa.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV_OK = True
except ImportError:  # pragma: no cover
    _CV_OK = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_OK = True
except ImportError:  # pragma: no cover - entorno sin torch
    _TORCH_OK = False
    nn = None

# Búsqueda del modelo entrenado, en orden: env var → modelo del repo (se
# distribuye con la app) → cache del usuario (donde lo deja tools/train_char_cnn).
_REPO_MODEL = Path(__file__).resolve().parent / "models" / "emnist_cnn.pt"
_CACHE_MODEL = os.path.expanduser("~/.cache/huevonitis_ml/emnist_cnn.pt")


def default_model_path() -> str:
    """Primera ruta de modelo que exista; si ninguna, la canónica del repo."""
    for p in (os.environ.get("H4_CHAR_CNN"), str(_REPO_MODEL), _CACHE_MODEL):
        if p and os.path.exists(p):
            return p
    return str(_REPO_MODEL)


DEFAULT_MODEL_PATH = default_model_path()

# EMNIST 'letters': labels 1..26 → 'a'..'z' (mayúsculas y minúsculas fusionadas).
N_CLASSES = 27  # índice 0 sin usar; 1..26 = a..z


if _TORCH_OK:
    class CharCNN(nn.Module):
        """CNN chico estilo EMNIST (28×28 → 26 letras). Igual que el entrenamiento."""

        def __init__(self, n: int = N_CLASSES):
            super().__init__()
            self.c1 = nn.Conv2d(1, 32, 3, padding=1)
            self.c2 = nn.Conv2d(32, 32, 3, padding=1)
            self.c3 = nn.Conv2d(32, 64, 3, padding=1)
            self.c4 = nn.Conv2d(64, 64, 3, padding=1)
            self.fc1 = nn.Linear(64 * 7 * 7, 128)
            self.fc2 = nn.Linear(128, n)
            self.drop = nn.Dropout(0.3)

        def forward(self, x):
            x = F.relu(self.c1(x))
            x = F.max_pool2d(F.relu(self.c2(x)), 2)
            x = F.relu(self.c3(x))
            x = F.max_pool2d(F.relu(self.c4(x)), 2)
            x = self.drop(x)
            x = x.flatten(1)
            x = self.drop(F.relu(self.fc1(x)))
            return self.fc2(x)
else:  # pragma: no cover
    CharCNN = None


def label_to_char(label: int) -> str:
    """Convierte un label EMNIST 'letters' (1..26) a su letra a..z."""
    if 1 <= label <= 26:
        return chr(ord("a") + label - 1)
    return "?"


def char_to_label(ch: str) -> int | None:
    """Letra a..z → label 1..26. Devuelve None si no es a..z (p. ej. ñ).

    Guard de longitud: un charset de plantilla puede traer tokens de 2 letras
    (ligaduras R10 como "qu"/"ll"/"ch"). Sin el `len(c) == 1`, la comparación
    `"a" <= "qu" <= "z"` es True en Python y `ord("qu")` revienta — eso mataba
    `extract_pdf_pages` entero apenas un preset de usuario con pares entraba en
    `augmented_presets()` (ver template_extract:663). Una ligadura no es una
    letra a-z clasificable por el CNN, así que None es la semántica correcta.
    """
    if not ch or len(ch) != 1:
        return None
    c = ch.lower()
    if "a" <= c <= "z":
        return ord(c) - ord("a") + 1
    return None


def preprocess_to_emnist(mask: np.ndarray) -> np.ndarray | None:
    """Lleva una máscara de tinta (255=tinta, fondo 0) al formato EMNIST 28×28.

    Recorta al bbox de la tinta, escala el lado mayor a 20 px (manteniendo
    proporción) y la centra en un lienzo 28×28 — el mismo encuadre con el que se
    entrena MNIST/EMNIST. Devuelve float32 en [0,1] o None si no hay tinta.
    """
    if not _CV_OK or mask is None or mask.size == 0:
        return None
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    h, w = crop.shape
    s = 20.0 / max(h, w)
    nh, nw = max(1, round(h * s)), max(1, round(w * s))
    res = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((28, 28), np.float32)
    oy, ox = (28 - nh) // 2, (28 - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = res
    return canvas / 255.0


class EMNISTCharClassifier:
    """Carga el CNN una vez y puntúa recortes. Seguro si falta torch/modelo."""

    def __init__(self, model_path: str | None = None):
        self._model = None
        self._ok = False
        self.model_path = model_path or default_model_path()
        if not (_TORCH_OK and _CV_OK):
            logger.info("EMNISTCharClassifier: torch/cv2 no disponibles")
            return
        if not os.path.exists(self.model_path):
            logger.info("EMNISTCharClassifier: modelo no encontrado en %s", self.model_path)
            return
        try:
            self._model = CharCNN()
            state = torch.load(self.model_path, map_location="cpu")
            self._model.load_state_dict(state)
            self._model.eval()
            self._ok = True
            logger.info("EMNISTCharClassifier: modelo cargado de %s", self.model_path)
        except Exception as exc:
            logger.warning("EMNISTCharClassifier: no se pudo cargar el modelo: %s", exc)
            self._model = None
            self._ok = False

    @property
    def available(self) -> bool:
        return self._ok

    def _probs(self, mask: np.ndarray):
        x = preprocess_to_emnist(mask)
        if x is None:
            return None
        with torch.no_grad():
            logits = self._model(torch.from_numpy(x).view(1, 1, 28, 28))
            return F.softmax(logits, dim=1)[0]

    def classify_batch(self, masks: list[np.ndarray]) -> np.ndarray | None:
        """Clasifica muchos recortes de una vez. Devuelve probs [n, 27] (np) o None.

        Las máscaras sin tinta producen una fila de ceros. Pensado para el
        alineador juez-de-cortes, que evalúa decenas de segmentos candidatos por
        línea: un único forward por lote en vez de uno por segmento.
        """
        if not self._ok or not masks:
            return None
        xs = []
        valid = []
        for i, m in enumerate(masks):
            x = preprocess_to_emnist(m)
            if x is not None:
                xs.append(x)
                valid.append(i)
        out = np.zeros((len(masks), N_CLASSES), dtype=np.float32)
        if not xs:
            return out
        batch = torch.from_numpy(np.stack(xs)).view(len(xs), 1, 28, 28)
        with torch.no_grad():
            probs = F.softmax(self._model(batch), dim=1).cpu().numpy()
        for row, i in enumerate(valid):
            out[i] = probs[row]
        return out

    def predict_topk(self, mask: np.ndarray, k: int = 3) -> list[tuple[str, float]]:
        """Top-k (letra, probabilidad) para un recorte. [] si no se puede."""
        if not self._ok:
            return []
        probs = self._probs(mask)
        if probs is None:
            return []
        order = probs.argsort(descending=True)[:k]
        return [(label_to_char(int(i)), float(probs[int(i)])) for i in order
                if int(i) >= 1]

    def score(self, mask: np.ndarray, expected_char: str) -> float | None:
        """P(expected_char) según el modelo. None si no aplica (ñ, sin modelo…)."""
        if not self._ok:
            return None
        label = char_to_label(expected_char)
        if label is None:
            return None
        probs = self._probs(mask)
        if probs is None:
            return None
        return float(probs[label])
