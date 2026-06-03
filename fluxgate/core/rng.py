"""Deterministic RNG wrapper.

Wraps :class:`random.Random` (Mersenne Twister, stable across CPython
versions) so the whole simulation is reproducible from a single integer seed.
A single ``Rng`` instance is threaded through map generation, wave generation
and the tick loop, guaranteeing that ``seed`` fully determines a playthrough
given identical inputs.
"""

from __future__ import annotations

import random
from typing import Sequence, TypeVar

T = TypeVar("T")


class Rng:
    def __init__(self, seed: int):
        self.seed = seed
        self._r = random.Random(seed)

    def randint(self, a: int, b: int) -> int:
        return self._r.randint(a, b)

    def random(self) -> float:
        return self._r.random()

    def uniform(self, a: float, b: float) -> float:
        return self._r.uniform(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return self._r.choice(seq)

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        return self._r.sample(list(seq), k)

    def shuffle(self, seq: list) -> None:
        self._r.shuffle(seq)

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def spawn_child(self, salt: int) -> "Rng":
        """Derive an independent sub-stream (used to isolate map vs wave RNG)."""
        return Rng((self.seed * 2654435761 + salt) & 0x7FFFFFFF)
