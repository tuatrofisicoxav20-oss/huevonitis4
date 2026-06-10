"""Ruido "de mano" para el renderer (Fase R3 — C10/C5/E1/E2/E5).

La mano no genera ruido uniforme ni blanco: sus desviaciones son gaussianas
(acotadas por el control motor) y CORRELACIONADAS en el tiempo (la pluma
deriva, no teletransporta). Este módulo da las dos primitivas:

  • tnorm: gaussiana truncada — reemplaza los random.uniform de jitter.
  • OUProcess: proceso de Ornstein-Uhlenbeck discreto (x_i = ρ·x_{i-1} + ε)
    acotado — deriva suave para baseline, slant, rotación y márgenes.

Todo recibe el ``rng: random.Random`` inyectado (I6): nada de random global,
así un seed reproduce el documento byte a byte.
"""
from __future__ import annotations

import random


def tnorm(rng: random.Random, mu: float, sigma: float,
          lo: float, hi: float) -> float:
    """Gaussiana truncada a [lo, hi] por re-muestreo (clamp como último recurso).

    Con σ=0 devuelve mu clampeado. El re-muestreo (hasta 8 intentos) conserva
    la forma de campana cerca de los bordes mejor que un clamp duro, que
    apilaría masa en los extremos.
    """
    if sigma <= 0:
        return min(hi, max(lo, mu))
    for _ in range(8):
        v = rng.gauss(mu, sigma)
        if lo <= v <= hi:
            return v
    return min(hi, max(lo, rng.gauss(mu, sigma)))


class OUProcess:
    """Ornstein-Uhlenbeck discreto y acotado: x_i = ρ·x_{i-1} + tnorm(0, σ).

    ρ∈[0,1) controla la memoria (0.85-0.9 ≈ deriva de mano); bound acota la
    excursión total. step() avanza y devuelve el valor nuevo.
    """

    def __init__(self, rng: random.Random, sigma: float, rho: float = 0.9,
                 bound: float = 0.0, start: float = 0.0):
        self.rng = rng
        self.sigma = max(0.0, sigma)
        self.rho = min(0.999, max(0.0, rho))
        self.bound = abs(bound)
        self.x = start

    def step(self) -> float:
        self.x = self.rho * self.x + tnorm(
            self.rng, 0.0, self.sigma,
            -4.0 * self.sigma if self.sigma > 0 else 0.0,
            4.0 * self.sigma if self.sigma > 0 else 0.0,
        )
        if self.bound > 0:
            self.x = min(self.bound, max(-self.bound, self.x))
        return self.x
