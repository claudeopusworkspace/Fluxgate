"""Cosmetic particle system (render-side only).

Particles never touch the simulation, so they can use their own RNG and float
freely without affecting determinism. They are spawned in response to sim
events (deaths, explosions, fire flashes, leaks) and ambient field drift.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

from . import draw
from .palette import RGB


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    radius: float
    color: RGB
    drag: float = 0.92
    gravity: float = 0.0


class ParticleSystem:
    def __init__(self):
        self.particles: List[Particle] = []
        self.rng = random.Random(1234)

    def burst(self, x: float, y: float, color: RGB, n: int = 14,
              speed: float = 180.0, life: float = 0.5, radius: float = 3.0,
              gravity: float = 0.0) -> None:
        for _ in range(n):
            a = self.rng.random() * math.tau
            s = speed * (0.3 + 0.7 * self.rng.random())
            self.particles.append(Particle(
                x, y, math.cos(a) * s, math.sin(a) * s,
                life, life * (0.6 + 0.6 * self.rng.random()),
                radius * (0.5 + self.rng.random()), color, gravity=gravity))

    def spark_line(self, x: float, y: float, color: RGB, n: int = 6) -> None:
        self.burst(x, y, color, n=n, speed=90, life=0.25, radius=2.0)

    def ambient(self, w: int, h: int) -> None:
        # rare slow drifting motes for atmosphere
        if self.rng.random() < 0.15:
            self.particles.append(Particle(
                self.rng.uniform(0, w), h + 5,
                self.rng.uniform(-6, 6), self.rng.uniform(-22, -10),
                4.0, 4.0, self.rng.uniform(1.0, 2.2),
                (90, 110, 170), drag=1.0))

    def update(self, dt: float) -> None:
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= p.drag
            p.vy *= p.drag
            alive.append(p)
        self.particles = alive

    def draw(self, surf) -> None:
        for p in self.particles:
            t = max(0.0, p.life / p.max_life)
            r = max(1, int(p.radius * t))
            draw.blit_glow(surf, (p.x, p.y), r * 3, p.color, intensity=0.8 * t)
