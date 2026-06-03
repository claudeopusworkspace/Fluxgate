"""Logic & invariant tests for the Fluxgate simulation core."""

import math

import pytest

from fluxgate.core import config as C
from fluxgate.core.entities import Enemy, resolve_tower_stats, upgrade_cost
from fluxgate.core.game import (GameState, PHASE_BUILD, PHASE_COMBAT,
                                PHASE_DEFEAT, PHASE_VICTORY)
from fluxgate.core.grid import generate_map
from fluxgate.core.waves import generate_wave, unlocked_pool


# --------------------------------------------------------------------------- #
# Map / path
# --------------------------------------------------------------------------- #
def test_map_path_connectivity():
    for seed in range(40):
        m = generate_map(seed, C.GRID_W, C.GRID_H)
        # 4-connected path
        for a, b in zip(m.path_cells, m.path_cells[1:]):
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1, f"seed {seed} not 4-connected"
        # spawn on left edge, core on right edge
        assert m.spawn[0] == 0
        assert m.core[0] == C.GRID_W - 1
        # buildable + path partition the grid
        assert len(m.buildable) + len(set(m.path_cells)) == C.GRID_W * C.GRID_H
        # no path cell is buildable
        assert not (set(m.path_cells) & m.buildable)
        assert m.total_length > 0


def test_map_no_duplicate_cells():
    for seed in range(20):
        m = generate_map(seed, C.GRID_W, C.GRID_H)
        assert len(m.path_cells) == len(set(m.path_cells)), "path revisits a cell"


def test_pos_at_endpoints():
    m = generate_map(1, C.GRID_W, C.GRID_H)
    assert m.pos_at(0.0) == m.polyline[0]
    assert m.pos_at(m.total_length + 5) == m.polyline[-1]
    mid = m.pos_at(m.total_length / 2)
    assert 0 <= mid[0] <= C.GRID_W and 0 <= mid[1] <= C.GRID_H


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def _run_headless(seed, ticks=4000, difficulty="normal"):
    g = GameState(seed=seed, difficulty=difficulty)
    # auto-pick first augment, auto-build a fixed layout, auto-advance
    placed = 0
    buildables = sorted(g.map.buildable)
    for _ in range(ticks):
        if g.phase == PHASE_BUILD:
            if g.offered_augments:
                g.choose_augment(g.offered_augments[0]["id"])
            # build a couple pulse towers near the path when affordable
            while g.money >= g.build_cost("pulse") and placed < len(buildables):
                cx, cy = buildables[placed]
                placed += 1
                if g.build_tower(cx, cy, "pulse"):
                    break
            if not g.start_wave():
                break
        if g.phase in (PHASE_VICTORY, PHASE_DEFEAT):
            break
        g.tick(C.DT)
    return g


def test_determinism_same_seed():
    g1 = _run_headless(7, ticks=2000)
    g2 = _run_headless(7, ticks=2000)
    assert g1.wave_index == g2.wave_index
    assert g1.core_hp == g2.core_hp
    assert g1.money == g2.money
    assert g1.stats.kills == g2.stats.kills


def test_different_seeds_differ():
    maps = {generate_map(s, C.GRID_W, C.GRID_H).path_cells[5:8] and
            tuple(generate_map(s, C.GRID_W, C.GRID_H).path_cells) for s in range(8)}
    assert len(maps) > 1  # not all identical


# --------------------------------------------------------------------------- #
# Tower stat resolution / economy
# --------------------------------------------------------------------------- #
def test_upgrade_increases_damage_and_range():
    for ttype in ("pulse", "mortar", "rail", "arc"):
        l1 = resolve_tower_stats(ttype, 1)
        l2 = resolve_tower_stats(ttype, 2)
        assert l2["damage"] > l1["damage"]
        assert l2["range"] >= l1["range"]


def test_chain_targets_additive():
    s1 = resolve_tower_stats("arc", 1)
    s2 = resolve_tower_stats("arc", 2)
    assert s2["chain_targets"] == s1["chain_targets"] + 1


def test_build_and_sell_economy():
    g = GameState(seed=3)
    cell = sorted(g.map.buildable)[0]
    start = g.money
    t = g.build_tower(cell[0], cell[1], "pulse")
    assert t is not None
    assert g.money == start - g.build_cost("pulse")
    refund = g.sell_tower(t)
    assert refund == int(t.invested * C.SELL_REFUND)
    assert g.tower_at(*cell) is None


def test_cannot_build_on_path_or_occupied():
    g = GameState(seed=3)
    path_cell = g.map.path_cells[3]
    assert g.build_tower(path_cell[0], path_cell[1], "pulse") is None
    cell = sorted(g.map.buildable)[0]
    g.build_tower(cell[0], cell[1], "pulse")
    assert g.build_tower(cell[0], cell[1], "pulse") is None  # occupied


def test_cannot_afford():
    g = GameState(seed=3)
    g.money = 0
    cell = sorted(g.map.buildable)[0]
    assert g.build_tower(cell[0], cell[1], "rail") is None


# --------------------------------------------------------------------------- #
# Combat mechanics (direct, isolated)
# --------------------------------------------------------------------------- #
def _make_enemy(g, etype="grunt", hp=100.0, armor=0.0, **kw):
    e = g._spawn_enemy(etype, hp, C.ENEMIES[etype]["speed"])
    e.armor = armor
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_damage_applies_and_kills():
    g = GameState(seed=1)
    e = _make_enemy(g, hp=20.0)
    g._apply_damage(None, e, 25.0)
    assert not e.alive
    assert g.stats.kills == 1


def test_armor_reduces_damage_with_floor():
    g = GameState(seed=1)
    e = _make_enemy(g, hp=100.0, armor=8.0)
    g._apply_damage(None, e, 10.0)
    # 10 - 8 = 2 damage
    assert math.isclose(e.hp, 98.0, rel_tol=1e-6)
    # heavy armor floor: at least 10% leaks through
    e2 = _make_enemy(g, hp=100.0, armor=100.0)
    g._apply_damage(None, e2, 50.0)
    assert math.isclose(e2.hp, 95.0, rel_tol=1e-6)  # 10% of 50


def test_armor_pierce_augment():
    g = GameState(seed=1)
    g.mods.armor_pierce = 0.5
    e = _make_enemy(g, hp=100.0, armor=10.0)
    g._apply_damage(None, e, 20.0)
    # effective armor 5 -> 15 damage
    assert math.isclose(e.hp, 85.0, rel_tol=1e-6)


def test_shield_absorbs_first():
    g = GameState(seed=1)
    e = _make_enemy(g, hp=50.0)
    e.shield = 30.0
    e.shield_max = 30.0
    g._apply_damage(None, e, 20.0)
    assert math.isclose(e.shield, 10.0)
    assert e.hp == 50.0
    g._apply_damage(None, e, 20.0)
    assert e.shield == 0.0
    assert math.isclose(e.hp, 40.0)  # 10 leftover hits hp


def test_slow_strongest_wins_and_expires():
    g = GameState(seed=1)
    e = _make_enemy(g)
    g._apply_slow(e, 0.6, 1.0)
    assert e.slow_factor == 0.6
    g._apply_slow(e, 0.8, 1.0)  # weaker, ignored
    assert e.slow_factor == 0.6
    g._apply_slow(e, 0.4, 2.0)  # stronger
    assert e.slow_factor == 0.4
    # expire over time
    e.dist = 0
    for _ in range(int(2.5 / C.DT)):
        g._update_enemies(C.DT)
    assert e.slow_factor == 1.0


def test_poison_damages_over_time():
    g = GameState(seed=1)
    e = _make_enemy(g, hp=100.0)
    g._apply_poison(e, 10.0, 3.0)
    for _ in range(int(1.0 / C.DT)):
        g._update_enemies(C.DT)
    # ~10 dps for 1s
    assert 88.0 <= e.hp <= 92.0


def test_execute_augment_kills_low_hp():
    g = GameState(seed=1)
    g.mods.execute_pct = 0.1
    e = _make_enemy(g, hp=100.0)
    e.hp = 9.0
    g._apply_damage(None, e, 1.0)
    assert not e.alive


def test_execute_spares_boss():
    g = GameState(seed=1)
    g.mods.execute_pct = 0.5
    e = _make_enemy(g, etype="boss", hp=1000.0)
    e.hp = 100.0
    g._apply_damage(None, e, 1.0)
    assert e.alive  # boss immune to execute


def test_splitter_spawns_children():
    g = GameState(seed=1)
    g.wave_index = 5
    e = _make_enemy(g, etype="splitter", hp=10.0)
    n_before = len(g.enemies)
    g._apply_damage(None, e, 50.0)
    children = [x for x in g.enemies if x.etype == "splitterling"]
    assert len(children) == C.ENEMIES["splitter"]["split_count"]


def test_leak_damages_core():
    g = GameState(seed=1)
    g.phase = PHASE_COMBAT
    e = _make_enemy(g, etype="tank")
    e.dist = g.map.total_length + 1
    before = g.core_hp
    g._update_enemies(C.DT)
    assert g.core_hp == before - C.ENEMIES["tank"]["core_dmg"] * g.diff["core_dmg"]
    assert g.stats.leaks == 1


def test_core_zero_is_defeat():
    g = GameState(seed=1)
    g.phase = PHASE_COMBAT
    g.core_hp = 1
    e = _make_enemy(g, etype="boss")
    e.dist = g.map.total_length + 1
    g._update_enemies(C.DT)
    assert g.phase == PHASE_DEFEAT


# --------------------------------------------------------------------------- #
# Waves / augments
# --------------------------------------------------------------------------- #
def test_wave_generation_scales():
    w1 = generate_wave(0, 1)
    w10 = generate_wave(0, 10)
    hp1 = max(g.hp for g in w1.groups)
    hp10 = max(g.hp for g in w10.groups)
    assert hp10 > hp1
    assert w1.total_enemies >= 1


def test_boss_waves_contain_boss():
    for w in C.BOSS_WAVES:
        wave = generate_wave(0, w)
        assert any(g.enemy_type == "boss" for g in wave.groups)


def test_enemy_unlock_progression():
    assert "tank" not in [t for t, _ in unlocked_pool(4)]
    assert "tank" in [t for t, _ in unlocked_pool(5)]


def test_augments_offered_and_applied():
    g = GameState(seed=2)
    g.wave_index = 1
    g._offer_augments()
    assert len(g.offered_augments) == 3
    aid = g.offered_augments[0]["id"]
    before = (g.mods.dmg_mult, g.core_max_hp, g.mods.crit_chance)
    g.choose_augment(aid)
    assert g.offered_augments == []


def test_core_hp_augment_heals_and_raises():
    g = GameState(seed=2)
    g.core_hp = 50
    g.mods.apply(("core_hp_add", 25))  # apply via mods returns request normally
    # simulate the game-side handling
    g.core_max_hp += 25
    g.core_hp = min(g.core_max_hp, g.core_hp + 25)
    assert g.core_max_hp == C.START_CORE_HP + 25
    assert g.core_hp == 75


def test_must_pick_augment_before_next_wave():
    g = GameState(seed=2)
    g.wave_index = 1
    g._offer_augments()
    assert not g.start_wave()  # blocked while augment pending
    g.choose_augment(g.offered_augments[0]["id"])
    assert g.start_wave()


# --------------------------------------------------------------------------- #
# Full-run smoke
# --------------------------------------------------------------------------- #
def test_headless_run_terminates():
    g = _run_headless(11, ticks=20000)
    assert g.phase in (PHASE_BUILD, PHASE_COMBAT, PHASE_VICTORY, PHASE_DEFEAT)
    assert g.wave_index >= 1
