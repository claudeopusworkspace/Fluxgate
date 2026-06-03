"""GameState: the deterministic simulation core.

Everything that affects gameplay lives here and depends only on stdlib + the
sibling core modules. The renderer and the headless balance harness both drive
the exact same ``GameState`` via ``tick(DT)``, guaranteeing that what you test
headlessly is what you play.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config as C
from .entities import (Effect, Enemy, Projectile, Tower, resolve_tower_stats,
                       upgrade_cost)
from .grid import GameMap, generate_map
from .rng import Rng
from .waves import Wave, generate_wave

# Game phases
PHASE_BUILD = "build"        # between waves; an augment choice may be pending
PHASE_COMBAT = "combat"
PHASE_VICTORY = "victory"
PHASE_DEFEAT = "defeat"


@dataclass
class Modifiers:
    """Global run-wide modifiers accumulated from augment picks."""
    dmg_mult: float = 1.0
    rate_mult: float = 1.0
    range_mult: float = 1.0
    money_mult: float = 1.0
    splash_mult: float = 1.0
    dot_mult: float = 1.0
    cost_mult: float = 1.0
    crit_chance: float = 0.0
    armor_pierce: float = 0.0
    hit_slow: float = 0.0
    chain_bonus: int = 0
    execute_pct: float = 0.0
    spillover: int = 0
    wave_income: int = 0

    def apply(self, mod: Tuple[str, float]) -> Optional[Tuple[str, float]]:
        """Apply an augment modifier. Returns a side-effect request for the
        game to handle immediately (e.g. core HP), else ``None``."""
        key, val = mod
        if key == "core_hp_add":
            return ("core_hp_add", val)
        if key in ("dmg_mult", "rate_mult", "range_mult", "money_mult",
                   "splash_mult", "dot_mult", "cost_mult"):
            setattr(self, key, getattr(self, key) + val)
            if key == "cost_mult":
                self.cost_mult = max(0.5, self.cost_mult)
            return None
        if key in ("crit_chance", "armor_pierce", "hit_slow"):
            cur = getattr(self, key)
            setattr(self, key, min(1.0, cur + val))
            return None
        if key in ("chain_bonus", "wave_income"):
            setattr(self, key, getattr(self, key) + int(val))
            return None
        if key == "execute_pct":
            self.execute_pct = max(self.execute_pct, val)
            return None
        if key == "spillover":
            self.spillover = 1
            return None
        return None


@dataclass
class Stats:
    kills: int = 0
    leaks: int = 0
    money_earned: int = 0
    money_spent: int = 0
    damage_dealt: float = 0.0
    waves_cleared: int = 0


class GameState:
    def __init__(self, seed: int = 0, difficulty: str = "normal",
                 map_obj: Optional[GameMap] = None):
        self.seed = seed
        self.difficulty = difficulty
        self.diff = C.DIFFICULTY[difficulty]
        self.map: GameMap = map_obj or generate_map(seed, C.GRID_W, C.GRID_H)

        self.combat_rng = Rng(seed).spawn_child(5000)
        self.augment_rng = Rng(seed).spawn_child(9000)

        self.money = int(self.diff.get("start_money", C.START_MONEY))
        self.core_hp = float(C.START_CORE_HP)
        self.core_max_hp = float(C.START_CORE_HP)

        self.phase = PHASE_BUILD
        self.wave_index = 0           # 0 == not started
        self.endless = False          # set once the player continues past wave 30
        self.time = 0.0               # total sim seconds
        self.mods = Modifiers()

        self.enemies: List[Enemy] = []
        self.towers: List[Tower] = []
        self.projectiles: List[Projectile] = []
        self.effects: List[Effect] = []

        self._tower_at: Dict[Tuple[int, int], Tower] = {}
        self._next_enemy_id = 1
        self._next_tower_id = 1
        self._next_proj_id = 1

        # wave runtime
        self.cur_wave: Optional[Wave] = None
        self._group_state: List[dict] = []   # per-group spawn tracking
        self.offered_augments: List[dict] = []

        self.stats = Stats()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    @property
    def victory(self) -> bool:
        return self.phase == PHASE_VICTORY

    @property
    def defeat(self) -> bool:
        return self.phase == PHASE_DEFEAT

    @property
    def alive_enemies(self) -> List[Enemy]:
        return [e for e in self.enemies if e.alive]

    def tower_at(self, cx: int, cy: int) -> Optional[Tower]:
        return self._tower_at.get((cx, cy))

    def build_cost(self, ttype: str) -> int:
        return int(round(C.TOWERS[ttype]["cost"] * self.mods.cost_mult))

    def upgrade_price(self, tower: Tower) -> Optional[int]:
        if tower.level >= C.TOWERS[tower.ttype]["max_level"] + 1:
            return None
        return int(round(upgrade_cost(tower.ttype, tower.level) * self.mods.cost_mult))

    # ------------------------------------------------------------------ #
    # Build / economy actions
    # ------------------------------------------------------------------ #
    def can_build(self, cx: int, cy: int, ttype: str) -> bool:
        if not self.map.is_buildable(cx, cy):
            return False
        if (cx, cy) in self._tower_at:
            return False
        return self.money >= self.build_cost(ttype)

    def build_tower(self, cx: int, cy: int, ttype: str) -> Optional[Tower]:
        if not self.can_build(cx, cy, ttype):
            return None
        cost = self.build_cost(ttype)
        self.money -= cost
        self.stats.money_spent += cost
        t = Tower(id=self._next_tower_id, ttype=ttype, cx=cx, cy=cy,
                  x=cx + 0.5, y=cy + 0.5, invested=cost)
        self._next_tower_id += 1
        self.towers.append(t)
        self._tower_at[(cx, cy)] = t
        self._recompute_buffs()
        return t

    def upgrade_tower(self, tower: Tower) -> bool:
        price = self.upgrade_price(tower)
        if price is None or self.money < price:
            return False
        self.money -= price
        self.stats.money_spent += price
        tower.invested += price
        tower.level += 1
        self._recompute_buffs()
        return True

    def sell_tower(self, tower: Tower) -> int:
        refund = int(tower.invested * C.SELL_REFUND)
        self.money += refund
        self.towers.remove(tower)
        self._tower_at.pop((tower.cx, tower.cy), None)
        self._recompute_buffs()
        return refund

    def set_target_mode(self, tower: Tower, mode: str) -> None:
        if mode in C.TARGET_MODES:
            tower.target_mode = mode

    def _recompute_buffs(self) -> None:
        """Recompute beacon auras onto each non-support tower."""
        beacons = [t for t in self.towers if C.TOWERS[t.ttype]["kind"] == "support"]
        for t in self.towers:
            t.buff_dmg = 0.0
            t.buff_rng = 0.0
        for b in beacons:
            bs = b.stats()
            r = bs["buff_radius"]
            for t in self.towers:
                if t is b or C.TOWERS[t.ttype]["kind"] == "support":
                    continue
                if math.hypot(t.x - b.x, t.y - b.y) <= r:
                    t.buff_dmg += bs["buff_damage"]
                    t.buff_rng += bs["buff_range"]

    # ------------------------------------------------------------------ #
    # Wave control
    # ------------------------------------------------------------------ #
    def start_wave(self) -> bool:
        """Begin the next wave. Disallowed if an augment choice is pending."""
        if self.phase != PHASE_BUILD:
            return False
        if self.offered_augments:
            return False
        self.wave_index += 1
        if self.mods.wave_income:
            self._gain_money(self.mods.wave_income, track=False)
        self.cur_wave = generate_wave(self.seed, self.wave_index, self.difficulty)
        self._group_state = [
            {"group": g, "spawned": 0, "timer": -g.delay} for g in self.cur_wave.groups
        ]
        self.phase = PHASE_COMBAT
        return True

    def _wave_spawning_done(self) -> bool:
        return all(gs["spawned"] >= gs["group"].count for gs in self._group_state)

    def _end_wave(self) -> None:
        bonus = C.WAVE_CLEAR_BONUS_BASE + C.WAVE_CLEAR_BONUS_GROWTH * self.wave_index
        bonus = int(bonus * self.diff["money"])
        self._gain_money(bonus)
        self.stats.waves_cleared += 1
        if not self.endless and self.wave_index >= C.TOTAL_WAVES:
            self.phase = PHASE_VICTORY
            return
        self._offer_augments()
        self.phase = PHASE_BUILD

    def _offer_augments(self) -> None:
        rng = self.augment_rng
        pool = list(C.AUGMENTS)
        weights = {"common": 3.0, "uncommon": 1.6, "rare": 0.7}
        chosen: List[dict] = []
        bag = pool[:]
        for _ in range(3):
            if not bag:
                break
            total = sum(weights[a["rarity"]] for a in bag)
            r = rng.random() * total
            acc = 0.0
            pick = bag[-1]
            for a in bag:
                acc += weights[a["rarity"]]
                if r <= acc:
                    pick = a
                    break
            chosen.append(pick)
            bag.remove(pick)
        self.offered_augments = chosen

    def choose_augment(self, augment_id: str) -> bool:
        for a in self.offered_augments:
            if a["id"] == augment_id:
                req = self.mods.apply(a["mod"])
                if req and req[0] == "core_hp_add":
                    self.core_max_hp += req[1]
                    self.core_hp = min(self.core_max_hp, self.core_hp + req[1])
                self.offered_augments = []
                return True
        return False

    def skip_augment(self) -> None:
        self.offered_augments = []

    def _gain_money(self, amount: int, track: bool = True) -> None:
        self.money += amount
        if track:
            self.stats.money_earned += amount

    # ------------------------------------------------------------------ #
    # Spawning
    # ------------------------------------------------------------------ #
    def _spawn_enemy(self, etype: str, hp: float, speed: float,
                     dist: float = 0.0) -> Enemy:
        spec = C.ENEMIES[etype]
        e = Enemy(
            id=self._next_enemy_id, etype=etype, max_hp=hp, hp=hp,
            base_speed=speed, armor=spec.get("armor", 0.0),
            reward=spec.get("reward", 1), core_dmg=spec.get("core_dmg", 1),
            size=spec.get("size", 0.3), dist=dist,
            shield=spec.get("shield", 0.0), shield_max=spec.get("shield", 0.0),
            shield_regen=spec.get("shield_regen", 0.0),
            shield_delay=spec.get("shield_delay", 2.0),
            regen=spec.get("regen", 0.0),
            heal_aura=spec.get("heal_aura", 0.0),
            heal_radius=spec.get("heal_radius", 0.0),
            split_into=spec.get("split_into"),
            split_count=spec.get("split_count", 0),
            phase_period=spec.get("phase_period", 0.0),
            phase_dur=spec.get("phase_dur", 0.0),
            is_boss=spec.get("boss", False),
        )
        self._next_enemy_id += 1
        px, py = self.map.pos_at(dist)
        e.x, e.y = px, py
        self.enemies.append(e)
        return e

    def _update_spawning(self, dt: float) -> None:
        for gs in self._group_state:
            g = gs["group"]
            if gs["spawned"] >= g.count:
                continue
            gs["timer"] += dt
            # spawn as many as are due this tick (handles fast intervals)
            while gs["spawned"] < g.count and gs["timer"] >= 0:
                self._spawn_enemy(g.enemy_type, g.hp, g.speed)
                gs["spawned"] += 1
                gs["timer"] -= g.interval

    # ------------------------------------------------------------------ #
    # Main tick
    # ------------------------------------------------------------------ #
    def tick(self, dt: float = C.DT) -> None:
        if self.phase not in (PHASE_COMBAT,):
            # still age effects so the UI stays lively between waves
            self._update_effects(dt)
            return
        self.time += dt
        self._update_spawning(dt)
        self._update_enemies(dt)
        self._update_towers(dt)
        self._update_projectiles(dt)
        self._cleanup()
        self._update_effects(dt)

        # wave completion
        if self._wave_spawning_done() and not self.alive_enemies:
            self._end_wave()

    # ---- enemy update ---- #
    def _update_enemies(self, dt: float) -> None:
        total_len = self.map.total_length
        healers = [e for e in self.enemies if e.alive and e.heal_aura > 0]
        for e in self.enemies:
            if not e.alive:
                continue
            # status timers
            if e.slow_timer > 0:
                e.slow_timer -= dt
                if e.slow_timer <= 0:
                    e.slow_factor = 1.0
            if e.poison_timer > 0:
                dmg = e.poison_dps * self.mods.dot_mult * dt
                e.hp -= dmg
                self.stats.damage_dealt += dmg
                e.poison_timer -= dt
            if e.regen > 0 and e.hp < e.max_hp:
                e.hp = min(e.max_hp, e.hp + e.regen * dt)
            # shield regen
            if e.shield_max > 0:
                e.shield_timer += dt
                if e.shield_timer >= e.shield_delay and e.shield < e.shield_max:
                    e.shield = min(e.shield_max, e.shield + e.shield_regen * dt)
            # phasing
            if e.phase_period > 0:
                e.phase_timer += dt
                e.phased = (e.phase_timer % e.phase_period) < e.phase_dur
            if e.hit_flash > 0:
                e.hit_flash -= dt
            if e.hp <= 0:
                self._kill(e, reward=True)
                continue
            # movement
            e.dist += e.speed * dt
            if e.dist >= total_len:
                self._leak(e)
                continue
            e.x, e.y = self.map.pos_at(e.dist)

        # healing aura pass (small n; O(n*healers))
        for h in healers:
            if not h.alive:
                continue
            for e in self.enemies:
                if e.alive and e is not h and e.hp < e.max_hp:
                    if math.hypot(e.x - h.x, e.y - h.y) <= h.heal_radius:
                        e.hp = min(e.max_hp, e.hp + h.heal_aura * dt)

    def _leak(self, e: Enemy) -> None:
        e.alive = False
        scale = 1.0 + C.LEAK_DMG_WAVE_SCALE * self.wave_index
        dmg = e.core_dmg * self.diff["core_dmg"] * scale
        self.core_hp -= dmg
        self.stats.leaks += 1
        self.effects.append(Effect("leak", 0.4, 0.4, x=self.map.polyline[-1][0],
                                    y=self.map.polyline[-1][1], radius=0.8,
                                    color="red"))
        if self.core_hp <= 0:
            self.core_hp = 0
            self.phase = PHASE_DEFEAT

    def _kill(self, e: Enemy, reward: bool) -> None:
        if not e.alive:
            return
        e.alive = False
        self.stats.kills += 1
        if reward:
            money = int(round(e.reward * C.REWARD_SCALE * self.mods.money_mult
                              * self.diff["money"]))
            self._gain_money(money)
        self.effects.append(Effect("death", 0.45, 0.45, x=e.x, y=e.y,
                                    radius=e.size * 2.4,
                                    color=C.ENEMIES[e.etype]["color"]))
        # splitting
        if e.split_into and e.split_count > 0:
            from .waves import child_hp
            chp = child_hp(e.split_into, max(1, self.wave_index), self.difficulty)
            cspec = C.ENEMIES[e.split_into]
            for i in range(e.split_count):
                child = self._spawn_enemy(
                    e.split_into, chp, cspec["speed"], dist=max(0.0, e.dist - 0.001))
                # fan them out slightly along the path so they don't overlap
                child.dist = max(0.0, e.dist - 0.25 * i)

    # ---- tower update ---- #
    def _update_towers(self, dt: float) -> None:
        for t in self.towers:
            if t.fire_flash > 0:
                t.fire_flash -= dt
            spec = C.TOWERS[t.ttype]
            if spec["kind"] == "support":
                continue
            if t.cooldown > 0:
                t.cooldown -= dt
            st = t.stats()
            rng_eff = st["range"] * self.mods.range_mult * (1.0 + t.buff_rng)
            target = self._acquire_target(t, rng_eff)
            if target is None:
                continue
            t.aim_angle = math.atan2(target.y - t.y, target.x - t.x)
            if t.cooldown > 0:
                continue
            fire_rate = st["fire_rate"] * self.mods.rate_mult
            if fire_rate <= 0:
                continue
            t.cooldown = 1.0 / fire_rate
            t.fire_flash = 0.08
            self._fire(t, st, target, rng_eff)

    def _enemies_in_range(self, x: float, y: float, r: float,
                          exclude_phased: bool = True) -> List[Enemy]:
        out = []
        r2 = r * r
        for e in self.enemies:
            if not e.alive:
                continue
            if exclude_phased and e.phased:
                continue
            dx = e.x - x
            dy = e.y - y
            if dx * dx + dy * dy <= r2:
                out.append(e)
        return out

    def _acquire_target(self, t: Tower, rng_eff: float) -> Optional[Enemy]:
        candidates = self._enemies_in_range(t.x, t.y, rng_eff)
        if not candidates:
            return None
        mode = t.target_mode
        if mode == C.TARGET_FIRST:
            return max(candidates, key=lambda e: e.dist)
        if mode == C.TARGET_LAST:
            return min(candidates, key=lambda e: e.dist)
        if mode == C.TARGET_CLOSEST:
            return min(candidates, key=lambda e: (e.x - t.x) ** 2 + (e.y - t.y) ** 2)
        if mode == C.TARGET_STRONGEST:
            return max(candidates, key=lambda e: e.effective_hp)
        if mode == C.TARGET_WEAKEST:
            return min(candidates, key=lambda e: e.effective_hp)
        return max(candidates, key=lambda e: e.dist)

    def _roll_crit(self) -> bool:
        return self.mods.crit_chance > 0 and self.combat_rng.chance(self.mods.crit_chance)

    def _base_damage(self, t: Tower, st: dict) -> Tuple[float, bool]:
        crit = self._roll_crit()
        dmg = st["damage"] * self.mods.dmg_mult * (1.0 + t.buff_dmg)
        if crit:
            dmg *= 2.0
        return dmg, crit

    def _fire(self, t: Tower, st: dict, target: Enemy, rng_eff: float) -> None:
        kind = st["kind"]
        if kind in ("bullet", "venom", "splash"):
            dmg, crit = self._base_damage(t, st)
            p = Projectile(
                id=self._next_proj_id, kind=kind, x=t.x, y=t.y,
                speed=st["projectile_speed"], damage=dmg, target_id=target.id,
                tower_id=t.id, last_x=target.x, last_y=target.y, crit=crit,
                splash_radius=st.get("splash_radius", 0.0) * self.mods.splash_mult,
                dot_dps=st.get("dot_dps", 0.0), dot_dur=st.get("dot_dur", 0.0),
                armor_shred=st.get("armor_shred", 0.0),
            )
            self._next_proj_id += 1
            self.projectiles.append(p)
        elif kind == "frost":
            self._fire_frost(t, st, target, rng_eff)
        elif kind == "chain":
            self._fire_chain(t, st, target)
        elif kind == "beam":
            self._fire_beam(t, st, target, rng_eff)

    def _fire_frost(self, t: Tower, st: dict, target: Enemy, rng_eff: float) -> None:
        dmg, crit = self._base_damage(t, st)
        radius = st.get("splash_radius", 1.0) * self.mods.splash_mult
        for e in self._enemies_in_range(target.x, target.y, radius):
            self._apply_damage(t, e, dmg, source_kind="frost")
            self._apply_slow(e, st["slow_factor"], st["slow_dur"])
        self.effects.append(Effect("frost", 0.35, 0.35, x=target.x, y=target.y,
                                    radius=radius, color="ice"))

    def _fire_chain(self, t: Tower, st: dict, first: Enemy) -> None:
        max_targets = int(st["chain_targets"]) + self.mods.chain_bonus
        falloff = st.get("chain_falloff", 0.7)
        chain_range = st.get("chain_range", 2.2)
        dmg, crit = self._base_damage(t, st)
        hit_ids = set()
        cur = first
        points = [(t.x, t.y)]
        cur_dmg = dmg
        for _ in range(max_targets):
            if cur is None:
                break
            self._apply_damage(t, cur, cur_dmg, source_kind="chain")
            hit_ids.add(cur.id)
            points.append((cur.x, cur.y))
            cur_dmg *= falloff
            # next: nearest unhit enemy within chain range
            nxt = None
            best = chain_range * chain_range
            for e in self.enemies:
                if not e.alive or e.id in hit_ids or e.phased:
                    continue
                d2 = (e.x - cur.x) ** 2 + (e.y - cur.y) ** 2
                if d2 <= best:
                    best = d2
                    nxt = e
            cur = nxt
        self.effects.append(Effect("chain", 0.18, 0.18, color="violet", points=points))

    def _fire_beam(self, t: Tower, st: dict, target: Enemy, rng_eff: float) -> None:
        dmg, crit = self._base_damage(t, st)
        pierce = st.get("pierce", False)
        # endpoint extended to range along aim direction
        ang = math.atan2(target.y - t.y, target.x - t.x)
        ex = t.x + math.cos(ang) * rng_eff
        ey = t.y + math.sin(ang) * rng_eff
        if pierce:
            # damage all enemies near the segment t->ex
            for e in self._line_targets(t.x, t.y, ex, ey, 0.45):
                self._apply_damage(t, e, dmg, source_kind="beam")
        else:
            self._apply_damage(t, target, dmg, source_kind="beam")
            ex, ey = target.x, target.y
        self.effects.append(Effect("beam", 0.12, 0.12, color="red",
                                    points=[(t.x, t.y), (ex, ey)]))

    def _line_targets(self, x0, y0, x1, y1, width) -> List[Enemy]:
        out = []
        dx = x1 - x0
        dy = y1 - y0
        seg_len2 = dx * dx + dy * dy
        if seg_len2 <= 1e-9:
            return out
        w2 = width * width
        for e in self.enemies:
            if not e.alive or e.phased:
                continue
            t = ((e.x - x0) * dx + (e.y - y0) * dy) / seg_len2
            t = max(0.0, min(1.0, t))
            px = x0 + t * dx
            py = y0 + t * dy
            if (e.x - px) ** 2 + (e.y - py) ** 2 <= w2:
                out.append(e)
        out.sort(key=lambda e: e.dist, reverse=True)
        return out

    # ---- projectile update ---- #
    def _update_projectiles(self, dt: float) -> None:
        for p in self.projectiles:
            if not p.alive:
                continue
            target = self._find_enemy(p.target_id)
            if target is not None and target.alive and not target.phased:
                p.last_x, p.last_y = target.x, target.y
                tx, ty = target.x, target.y
            else:
                target = None
                tx, ty = p.last_x, p.last_y
            dx = tx - p.x
            dy = ty - p.y
            dist = math.hypot(dx, dy)
            step = p.speed * dt
            if dist <= step or dist < 1e-6:
                # arrival
                p.x, p.y = tx, ty
                self._resolve_projectile(p, target)
                p.alive = False
            else:
                p.x += dx / dist * step
                p.y += dy / dist * step

    def _resolve_projectile(self, p: Projectile, target: Optional[Enemy]) -> None:
        tower = self._find_tower(p.tower_id)
        if p.kind == "splash":
            radius = p.splash_radius
            for e in self._enemies_in_range(p.x, p.y, radius):
                self._apply_damage(tower, e, p.damage, source_kind="splash",
                                   precomputed=True)
            self.effects.append(Effect("explosion", 0.4, 0.4, x=p.x, y=p.y,
                                        radius=radius, color="orange"))
        else:
            if target is None or not target.alive:
                return  # single-target shot fizzles on a dead target
            self._apply_damage(tower, target, p.damage, source_kind=p.kind,
                               precomputed=True)
            if p.kind == "venom":
                self._apply_poison(target, p.dot_dps, p.dot_dur)
                target.armor = max(0.0, target.armor - p.armor_shred)
                self.effects.append(Effect("venomhit", 0.3, 0.3, x=target.x,
                                            y=target.y, radius=0.4, color="toxic"))

    # ---- damage / effects ---- #
    def _apply_damage(self, tower: Optional[Tower], e: Enemy, raw: float,
                      source_kind: str = "", precomputed: bool = False) -> None:
        if not e.alive:
            return
        # armor (with global pierce)
        eff_armor = e.armor * (1.0 - self.mods.armor_pierce)
        dmg = max(raw - eff_armor, raw * 0.10)
        # global on-hit slow augment
        if self.mods.hit_slow > 0:
            self._apply_slow(e, 1.0 - self.mods.hit_slow, 0.8)
        # shield soak
        if e.shield > 0:
            soak = min(e.shield, dmg)
            e.shield -= soak
            dmg -= soak
            e.shield_timer = 0.0
        e.hp -= dmg
        e.hit_flash = 0.12
        self.stats.damage_dealt += dmg
        if tower is not None:
            tower.damage_dealt += dmg
        # execute
        if (self.mods.execute_pct > 0 and not e.is_boss and e.hp > 0
                and e.hp <= e.max_hp * self.mods.execute_pct):
            e.hp = 0
        if e.hp <= 0:
            overkill = -e.hp
            if tower is not None:
                tower.kills += 1
            self._kill(e, reward=True)
            # spillover augment: dump overkill onto nearest other enemy
            if self.mods.spillover and overkill > 0:
                nxt = self._nearest_other(e)
                if nxt is not None:
                    self._apply_damage(tower, nxt, overkill, source_kind="spillover")

    def _apply_slow(self, e: Enemy, factor: float, dur: float) -> None:
        # stronger slow wins; duration refreshed
        if factor < e.slow_factor:
            e.slow_factor = factor
        e.slow_timer = max(e.slow_timer, dur)

    def _apply_poison(self, e: Enemy, dps: float, dur: float) -> None:
        if dps >= e.poison_dps:
            e.poison_dps = dps
        e.poison_timer = max(e.poison_timer, dur)

    def _nearest_other(self, src: Enemy) -> Optional[Enemy]:
        best = None
        bd = 9999.0
        for e in self.enemies:
            if e.alive and e is not src and not e.phased:
                d = (e.x - src.x) ** 2 + (e.y - src.y) ** 2
                if d < bd:
                    bd = d
                    best = e
        return best

    def _find_enemy(self, eid: int) -> Optional[Enemy]:
        for e in self.enemies:
            if e.id == eid:
                return e
        return None

    def _find_tower(self, tid: int) -> Optional[Tower]:
        for t in self.towers:
            if t.id == tid:
                return t
        return None

    def _update_effects(self, dt: float) -> None:
        for fx in self.effects:
            fx.ttl -= dt
        self.effects = [fx for fx in self.effects if fx.ttl > 0]

    def _cleanup(self) -> None:
        self.enemies = [e for e in self.enemies if e.alive]
        self.projectiles = [p for p in self.projectiles if p.alive]
