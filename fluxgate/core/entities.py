"""Simulation entities and per-level stat resolution.

Pure data + a little math; no rendering, no global state. Entities are plain
dataclasses mutated by :mod:`fluxgate.core.game`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config as C

# Upgrade keys that add (rather than multiply) per level.
_ADDITIVE_UPGRADE_KEYS = {"chain_targets"}


def resolve_tower_stats(ttype: str, level: int) -> dict:
    """Return effective base stats for a tower at ``level`` (1-indexed).

    Upgrade growth from ``config`` is applied ``level-1`` times: multiplicative
    for most fields, additive for keys in ``_ADDITIVE_UPGRADE_KEYS``.
    """
    spec = C.TOWERS[ttype]
    stats = dict(spec)  # shallow copy of all fields
    up = spec.get("upgrade", {})
    steps = level - 1
    for key, growth in up.items():
        if key == "cost_factor":
            continue
        if key not in stats:
            continue
        if key in _ADDITIVE_UPGRADE_KEYS:
            stats[key] = stats[key] + growth * steps
        else:
            stats[key] = stats[key] * (growth ** steps)
    return stats


def upgrade_cost(ttype: str, current_level: int) -> int:
    spec = C.TOWERS[ttype]
    cf = spec.get("upgrade", {}).get("cost_factor", 0.9)
    return int(round(spec["cost"] * cf * current_level))


@dataclass
class Enemy:
    id: int
    etype: str
    max_hp: float
    hp: float
    base_speed: float
    armor: float
    reward: int
    core_dmg: int
    size: float
    dist: float = 0.0
    x: float = 0.0
    y: float = 0.0
    alive: bool = True
    # status
    slow_factor: float = 1.0
    slow_timer: float = 0.0
    poison_dps: float = 0.0
    poison_timer: float = 0.0
    # shield
    shield: float = 0.0
    shield_max: float = 0.0
    shield_regen: float = 0.0
    shield_delay: float = 2.0
    shield_timer: float = 0.0
    # specials
    regen: float = 0.0
    heal_aura: float = 0.0
    heal_radius: float = 0.0
    split_into: Optional[str] = None
    split_count: int = 0
    phase_period: float = 0.0
    phase_dur: float = 0.0
    phase_timer: float = 0.0
    phased: bool = False
    is_boss: bool = False
    # bookkeeping for renderers (hit flash etc.)
    hit_flash: float = 0.0

    @property
    def speed(self) -> float:
        return self.base_speed * self.slow_factor

    @property
    def effective_hp(self) -> float:
        return self.hp + self.shield


@dataclass
class Projectile:
    id: int
    kind: str               # bullet | splash | venom
    x: float
    y: float
    speed: float
    damage: float
    target_id: int
    tower_id: int
    last_x: float
    last_y: float
    crit: bool = False
    # carried effect payloads
    splash_radius: float = 0.0
    dot_dps: float = 0.0
    dot_dur: float = 0.0
    armor_shred: float = 0.0
    alive: bool = True


@dataclass
class Tower:
    id: int
    ttype: str
    cx: int
    cy: int
    x: float
    y: float
    level: int = 1
    cooldown: float = 0.0
    target_mode: str = C.TARGET_FIRST
    invested: int = 0
    kills: int = 0
    damage_dealt: float = 0.0
    # cached beacon buffs (recomputed on topology change)
    buff_dmg: float = 0.0
    buff_rng: float = 0.0
    # render aid
    aim_angle: float = 0.0
    fire_flash: float = 0.0

    def stats(self) -> dict:
        return resolve_tower_stats(self.ttype, self.level)


@dataclass
class Effect:
    """Transient visual/logic effect (beam, chain, frost burst, explosion).

    Lives in the sim so headless runs stay deterministic and the renderer can
    simply read them. ``points`` holds polyline vertices for beams/chains.
    """
    kind: str
    ttl: float
    max_ttl: float
    x: float = 0.0
    y: float = 0.0
    radius: float = 0.0
    color: str = "white"
    points: List[Tuple[float, float]] = field(default_factory=list)
