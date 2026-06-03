"""Procedural wave generation.

A wave is a list of *spawn groups*. Each group emits ``count`` enemies of one
type, spaced ``interval`` seconds apart, after an initial ``delay``. Waves are
built from a per-wave "threat budget" spent on the currently-unlocked enemy
pool, so difficulty ramps smoothly and new enemy archetypes appear on schedule.
HP/speed scaling is computed here and baked into each spawn so the tick loop
stays simple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from . import config as C
from .rng import Rng


@dataclass
class SpawnGroup:
    enemy_type: str
    count: int
    interval: float
    delay: float
    hp: float
    speed: float


@dataclass
class Wave:
    index: int
    groups: List[SpawnGroup]

    @property
    def total_enemies(self) -> int:
        return sum(g.count for g in self.groups)


def _hp_scale(wave: int, difficulty: str = "normal") -> float:
    growth = C.DIFFICULTY[difficulty].get("hp_growth", C.HP_BASE_GROWTH)
    return growth ** (wave - 1)


def _speed_scale(wave: int) -> float:
    return C.SPEED_GROWTH ** (wave - 1)


def unlocked_pool(wave: int) -> list[tuple[str, float]]:
    pool: list[tuple[str, float]] = []
    for unlock_wave, entries in C.ENEMY_UNLOCK:
        if wave >= unlock_wave:
            pool.extend(entries)
    return pool


def generate_wave(seed: int, wave: int, difficulty: str = "normal") -> Wave:
    """Build a single wave deterministically from (seed, wave)."""
    rng = Rng(seed).spawn_child(1000 + wave)
    diff = C.DIFFICULTY[difficulty]
    hp_scale = _hp_scale(wave, difficulty)
    spd_scale = _speed_scale(wave)
    budget = C.BUDGET_BASE * (diff["budget_growth"] ** (wave - 1))

    pool = unlocked_pool(wave)
    groups: List[SpawnGroup] = []

    # Boss waves: spend most budget on a boss + a support escort.
    is_boss = wave in C.BOSS_WAVES
    if is_boss:
        boss_hp = C.ENEMIES["boss"]["base_hp"] * hp_scale * (1.0 + 0.15 * (wave // 10))
        groups.append(SpawnGroup("boss", 1, 1.0, 0.0,
                                 hp=boss_hp,
                                 speed=C.ENEMIES["boss"]["speed"] * spd_scale))
        budget *= 0.6  # escort budget

    delay = 0.0
    guard = 0
    while budget > 0 and guard < 250:
        guard += 1
        etype, cost = rng.choice(pool)
        spec = C.ENEMIES[etype]
        # how many to send: scale group size with budget, clamp sensibly
        max_n = max(1, int(budget / cost))
        n = rng.randint(1, min(max_n, 14 if spec["base_hp"] < 40 else 8))
        budget -= n * cost
        interval = rng.uniform(0.35, 0.9) if spec["speed"] < 2.6 else rng.uniform(0.25, 0.55)
        groups.append(SpawnGroup(
            enemy_type=etype,
            count=n,
            interval=interval,
            delay=delay,
            hp=spec["base_hp"] * hp_scale,
            speed=spec["speed"] * spd_scale,
        ))
        delay += rng.uniform(0.6, 2.2)

    # Always guarantee at least one group.
    if not groups:
        spec = C.ENEMIES["grunt"]
        groups.append(SpawnGroup("grunt", 5, 0.6, 0.0,
                                 hp=spec["base_hp"] * hp_scale,
                                 speed=spec["speed"] * spd_scale))

    return Wave(index=wave, groups=groups)


def child_hp(parent_hp_fraction_type: str, wave: int, difficulty: str) -> float:
    """HP for a split child (e.g. splitterling) at the given wave."""
    spec = C.ENEMIES[parent_hp_fraction_type]
    return spec["base_hp"] * _hp_scale(wave, difficulty)
