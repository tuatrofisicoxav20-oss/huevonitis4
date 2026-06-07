"""Entrena el CNN clasificador de caracteres (EMNIST 'letters') para Huevonitis.

Genera el modelo que usa core/inkcore/ai/char_cnn.py como JUEZ de los cortes del
extractor (over-segmentación + selección guiada por reconocimiento). NO es un OCR
de línea: clasifica un carácter ya recortado (a..z; la ñ no existe en EMNIST).

Uso:
    python3 tools/train_char_cnn.py [--epochs 5] [--out RUTA]

Por defecto guarda en ~/.cache/huevonitis_ml/emnist_cnn.pt (la ruta que busca
EMNISTCharClassifier). Descarga EMNIST la primera vez (~562 MB) a ese mismo dir.
Requiere torch + torchvision (opcionales del proyecto). Entrena en CPU en pocos
minutos; el RandomAffine ayuda a generalizar a letra real (fuera de EMNIST).
"""
from __future__ import annotations

import argparse
import os
import time

import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from core.inkcore.ai.char_cnn import CharCNN  # misma arquitectura que inferencia

DEFAULT_OUT = os.path.expanduser("~/.cache/huevonitis_ml/emnist_cnn.pt")


def _untranspose(im):
    """Des-transpone la orientación característica de EMNIST (función nombrada
    para que el DataLoader con num_workers>0 pueda picklear el transform)."""
    return im.transpose(Image.TRANSPOSE)


def build_loaders(root: str, batch: int = 256):
    tf = transforms.Compose([
        _untranspose,
        transforms.RandomAffine(degrees=10, translate=(0.08, 0.08), scale=(0.9, 1.1)),
        transforms.ToTensor(),
    ])
    tf_test = transforms.Compose([_untranspose, transforms.ToTensor()])
    tr = datasets.EMNIST(root, split="letters", train=True, download=True, transform=tf)
    te = datasets.EMNIST(root, split="letters", train=False, download=True, transform=tf_test)
    return (DataLoader(tr, batch_size=batch, shuffle=True, num_workers=2),
            DataLoader(te, batch_size=512, num_workers=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--root", default=os.path.expanduser("~/.cache/huevonitis_ml"))
    args = ap.parse_args()
    os.makedirs(args.root, exist_ok=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    trl, tel = build_loaders(args.root)
    model = CharCNN()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    t0 = time.time()
    for ep in range(args.epochs):
        model.train()
        tl = 0.0
        for xb, yb in trl:
            opt.zero_grad()
            loss = F.cross_entropy(model(xb), yb)
            loss.backward()
            opt.step()
            tl += float(loss)
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for xb, yb in tel:
                correct += int((model(xb).argmax(1) == yb).sum())
                total += len(yb)
        print(f"epoch {ep+1}/{args.epochs} loss={tl/len(trl):.3f} "
              f"test_acc={correct/total:.3f} ({time.time()-t0:.0f}s)", flush=True)
    torch.save(model.state_dict(), args.out)
    print("GUARDADO:", args.out, flush=True)


if __name__ == "__main__":
    main()
