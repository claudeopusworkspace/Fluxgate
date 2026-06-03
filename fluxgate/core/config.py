"""Central balance configuration for Fluxgate.

All tunable numbers live here so the balance harness has a single source of
truth. The simulation core imports only stdlib + this module.

Units:
  * Distance is measured in grid cells (1 cell == 1.0).
  * Time is measured in seconds. Speeds/rates are per-second and multiplied
    by the fixed timestep ``DT`` each tick.
"""

# --- World / timing -------------------------------------------------------
GRID_W = 22
GRID_H = 14
DT = 1.0 / 30.0          # fixed simulation timestep (seconds)

# --- Economy / run setup --------------------------------------------------
START_MONEY = 130
START_CORE_HP = 80
WAVE_CLEAR_BONUS_BASE = 10      # money granted when a wave is fully cleared
WAVE_CLEAR_BONUS_GROWTH = 2     # added per wave index
SELL_REFUND = 0.7               # fraction of total invested returned on sell
LEAK_DMG_WAVE_SCALE = 0.06      # leaks hurt more as waves progress
REWARD_SCALE = 0.6              # global kill-reward scalar (caps tower economy)

TOTAL_WAVES = 30                # surviving this many == "victory" (endless after)

# --- Difficulty presets ---------------------------------------------------
# Difficulty steepens the *growth curve* rather than applying a flat HP
# multiplier, so every tier opens at a similar, learnable pace and only
# diverges in the late game. (A flat multiplier would just wall the early
# waves, which is an instant loss, not a difficulty curve.)
DIFFICULTY = {
    "easy":   {"hp_growth": 1.175, "budget_growth": 1.05, "money": 1.15,
               "core_dmg": 0.85, "start_money": 170},
    "normal": {"hp_growth": 1.200, "budget_growth": 1.06, "money": 1.00,
               "core_dmg": 1.00, "start_money": 130},
    "hard":   {"hp_growth": 1.225, "budget_growth": 1.07, "money": 0.95,
               "core_dmg": 1.15, "start_money": 120},
    "insane": {"hp_growth": 1.250, "budget_growth": 1.08, "money": 0.90,
               "core_dmg": 1.35, "start_money": 110},
}

# --- Targeting modes ------------------------------------------------------
TARGET_FIRST = "first"        # furthest along the path (closest to core)
TARGET_LAST = "last"
TARGET_CLOSEST = "closest"
TARGET_STRONGEST = "strongest"
TARGET_WEAKEST = "weakest"
TARGET_MODES = [TARGET_FIRST, TARGET_LAST, TARGET_CLOSEST, TARGET_STRONGEST, TARGET_WEAKEST]

# --- Tower specifications -------------------------------------------------
# Each tower has base stats and a per-level multiplier set. ``max_level`` is
# the number of upgrade tiers above level 1 (so level ranges 1..max_level+1).
#
# fields:
#   name, color (hue id for palette), cost
#   range, damage, fire_rate (shots/sec)
#   kind: "bullet" | "splash" | "beam" | "chain" | "frost" | "venom" | "support"
#   projectile_speed (cells/sec; 0 == instant/beam)
#   splash_radius, slow_factor, slow_dur, dot_dps, dot_dur, armor_shred
#   chain_targets, chain_falloff
#   buff_damage, buff_range, buff_radius (support)
#   upgrade: dict of per-level multiplicative growth + flat upgrade cost factor
#   targets_flag: which enemies it can hit ("all" | "ground")
TOWERS = {
    "pulse": {
        "name": "Pulse",
        "color": "cyan",
        "cost": 60,
        "range": 3.2,
        "damage": 14.0,
        "fire_rate": 1.6,
        "kind": "bullet",
        "projectile_speed": 14.0,
        "desc": "Reliable single-target gun. Solid all-rounder.",
        "max_level": 3,
        "upgrade": {"damage": 1.55, "range": 1.08, "fire_rate": 1.12, "cost_factor": 0.85},
    },
    "splinter": {
        "name": "Splinter",
        "color": "lime",
        "cost": 75,
        "range": 2.7,
        "damage": 5.0,
        "fire_rate": 4.5,
        "kind": "bullet",
        "projectile_speed": 18.0,
        "desc": "Rapid low-damage darts. Shreds swarms.",
        "max_level": 3,
        "upgrade": {"damage": 1.4, "range": 1.06, "fire_rate": 1.18, "cost_factor": 0.8},
    },
    "mortar": {
        "name": "Mortar",
        "color": "orange",
        "cost": 110,
        "range": 4.0,
        "damage": 26.0,
        "fire_rate": 0.55,
        "kind": "splash",
        "projectile_speed": 8.0,
        "splash_radius": 1.5,
        "desc": "Lobbed shells with area blast. Great vs clusters.",
        "max_level": 3,
        "upgrade": {"damage": 1.5, "range": 1.05, "fire_rate": 1.15, "splash_radius": 1.12, "cost_factor": 0.9},
    },
    "frost": {
        "name": "Frost",
        "color": "ice",
        "cost": 80,
        "range": 3.0,
        "damage": 4.0,
        "fire_rate": 1.2,
        "kind": "frost",
        "projectile_speed": 0.0,
        "splash_radius": 1.3,
        "slow_factor": 0.5,
        "slow_dur": 1.4,
        "desc": "Chilling burst that slows everything it touches.",
        "max_level": 3,
        "upgrade": {"damage": 1.3, "range": 1.06, "slow_factor": 0.9, "splash_radius": 1.1, "cost_factor": 0.85},
    },
    "arc": {
        "name": "Arc",
        "color": "violet",
        "cost": 130,
        "range": 3.4,
        "damage": 16.0,
        "fire_rate": 1.1,
        "kind": "chain",
        "projectile_speed": 0.0,
        "chain_targets": 3,
        "chain_falloff": 0.7,
        "chain_range": 2.2,
        "desc": "Lightning that leaps between nearby foes.",
        "max_level": 3,
        "upgrade": {"damage": 1.45, "range": 1.06, "fire_rate": 1.1, "chain_targets": 1, "cost_factor": 0.92},
    },
    "rail": {
        "name": "Railgun",
        "color": "red",
        "cost": 160,
        "range": 6.0,
        "damage": 95.0,
        "fire_rate": 0.4,
        "kind": "beam",
        "projectile_speed": 0.0,
        "pierce": True,
        "desc": "Long-range hitscan slug that punches through armor & a line of foes.",
        "max_level": 3,
        "upgrade": {"damage": 1.6, "range": 1.07, "fire_rate": 1.18, "cost_factor": 0.95},
    },
    "venom": {
        "name": "Venom",
        "color": "toxic",
        "cost": 95,
        "range": 3.0,
        "damage": 3.0,
        "fire_rate": 1.0,
        "kind": "venom",
        "projectile_speed": 12.0,
        "dot_dps": 10.0,
        "dot_dur": 3.0,
        "armor_shred": 3.0,
        "desc": "Corrosive rounds: damage-over-time and armor shred.",
        "max_level": 3,
        "upgrade": {"damage": 1.2, "dot_dps": 1.5, "range": 1.05, "armor_shred": 1.4, "cost_factor": 0.88},
    },
    "beacon": {
        "name": "Beacon",
        "color": "gold",
        "cost": 120,
        "range": 0.0,
        "damage": 0.0,
        "fire_rate": 0.0,
        "kind": "support",
        "projectile_speed": 0.0,
        "buff_radius": 2.6,
        "buff_damage": 0.22,   # +22% damage to towers in radius
        "buff_range": 0.12,    # +12% range
        "desc": "Projects an aura that amplifies nearby towers.",
        "max_level": 2,
        "upgrade": {"buff_damage": 1.4, "buff_radius": 1.15, "buff_range": 1.3, "cost_factor": 1.0},
    },
}

TOWER_ORDER = ["pulse", "splinter", "mortar", "frost", "arc", "rail", "venom", "beacon"]

# --- Enemy specifications -------------------------------------------------
# fields: name, color, base_hp, speed (cells/sec), armor, reward, core_dmg, size
# abilities: flags handled by the sim.
#   regen (hp/sec), shield (pool), shield_regen, heal_aura (hp/sec to allies),
#   heal_radius, split_into (type) + split_count, phase_period/phase_dur,
#   boss (bool)
ENEMIES = {
    "grunt": {
        "name": "Grunt", "color": "steel", "base_hp": 36.0, "speed": 1.7,
        "armor": 0.0, "reward": 4, "core_dmg": 1, "size": 0.34,
    },
    "runner": {
        "name": "Runner", "color": "yellow", "base_hp": 18.0, "speed": 3.1,
        "armor": 0.0, "reward": 2, "core_dmg": 1, "size": 0.26,
    },
    "tank": {
        "name": "Tank", "color": "rust", "base_hp": 130.0, "speed": 1.0,
        "armor": 6.0, "reward": 7, "core_dmg": 3, "size": 0.46,
    },
    "mite": {
        "name": "Mite", "color": "pink", "base_hp": 9.0, "speed": 2.3,
        "armor": 0.0, "reward": 1, "core_dmg": 1, "size": 0.2,
    },
    "shielded": {
        "name": "Warden", "color": "azure", "base_hp": 50.0, "speed": 1.5,
        "armor": 2.0, "reward": 8, "core_dmg": 2, "size": 0.38,
        "shield": 60.0, "shield_regen": 14.0, "shield_delay": 2.5,
    },
    "healer": {
        "name": "Mender", "color": "green", "base_hp": 60.0, "speed": 1.4,
        "armor": 1.0, "reward": 10, "core_dmg": 2, "size": 0.36,
        "heal_aura": 7.0, "heal_radius": 2.4,
    },
    "splitter": {
        "name": "Splitter", "color": "magenta", "base_hp": 70.0, "speed": 1.4,
        "armor": 1.0, "reward": 10, "core_dmg": 2, "size": 0.4,
        "split_into": "splitterling", "split_count": 3,
    },
    "splitterling": {
        "name": "Shard", "color": "magenta", "base_hp": 16.0, "speed": 2.0,
        "armor": 0.0, "reward": 3, "core_dmg": 1, "size": 0.24,
    },
    "phantom": {
        "name": "Phantom", "color": "spectral", "base_hp": 44.0, "speed": 1.9,
        "armor": 0.0, "reward": 7, "core_dmg": 2, "size": 0.34,
        "phase_period": 3.2, "phase_dur": 1.1,   # periodically untargetable
    },
    "boss": {
        "name": "Colossus", "color": "boss", "base_hp": 1400.0, "speed": 0.85,
        "armor": 10.0, "reward": 90, "core_dmg": 12, "size": 0.7,
        "boss": True, "regen": 22.0,
    },
}

# --- Wave generation tuning ----------------------------------------------
# Enemy HP grows with wave; budgets grow too. New enemy types unlock at waves.
# HP grows fast (the real difficulty lever); enemy *count* grows slowly so
# kill-income — and therefore the affordable tower count — stays bounded while
# enemy EHP outpaces achievable DPS in the late game. This is what creates a
# genuine difficulty curve instead of a runaway economy feedback loop.
HP_BASE_GROWTH = 1.20           # per-wave hp multiplier (compounding)
SPEED_GROWTH = 1.006            # gentle speed creep
BUDGET_BASE = 20.0              # "threat budget" spent on enemies in wave 1
BUDGET_GROWTH = 1.06            # per-wave budget multiplier (count growth)

# unlock wave -> list of enemy types added to the pool, with a threat cost.
ENEMY_UNLOCK = [
    (1,  [("grunt", 1.0), ("runner", 0.8)]),
    (3,  [("mite", 0.35)]),
    (5,  [("tank", 4.0)]),
    (7,  [("shielded", 3.2)]),
    (9,  [("splitter", 3.0)]),
    (12, [("phantom", 3.0)]),
    (15, [("healer", 3.5)]),
]
BOSS_WAVES = {10, 20, 30}       # bosses appear on these waves

# --- Augment (roguelite upgrade) definitions ------------------------------
# Applied as global modifiers. Offered as 3 random cards between waves.
# Each: id, name, desc, rarity, and the modifier it sets/increments.
AUGMENTS = [
    {"id": "dmg1", "name": "Overcharge", "rarity": "common",
     "desc": "+15% global tower damage.", "mod": ("dmg_mult", 0.15)},
    {"id": "rate1", "name": "Rapid Cycling", "rarity": "common",
     "desc": "+12% global fire rate.", "mod": ("rate_mult", 0.12)},
    {"id": "range1", "name": "Optics Array", "rarity": "common",
     "desc": "+10% global tower range.", "mod": ("range_mult", 0.10)},
    {"id": "crit1", "name": "Weak-Point Scan", "rarity": "uncommon",
     "desc": "+12% crit chance (2.0x damage).", "mod": ("crit_chance", 0.12)},
    {"id": "money1", "name": "Salvage Drones", "rarity": "common",
     "desc": "+20% money from kills.", "mod": ("money_mult", 0.20)},
    {"id": "pierce_armor", "name": "AP Rounds", "rarity": "uncommon",
     "desc": "Ignore 50% of enemy armor.", "mod": ("armor_pierce", 0.50)},
    {"id": "slow_hit", "name": "Cryo Coating", "rarity": "uncommon",
     "desc": "All hits slow enemies by 15% for 0.8s.", "mod": ("hit_slow", 0.15)},
    {"id": "chain_plus", "name": "Conductive Field", "rarity": "uncommon",
     "desc": "+1 chain bounce on all chain towers.", "mod": ("chain_bonus", 1)},
    {"id": "splash_plus", "name": "Wide Payload", "rarity": "uncommon",
     "desc": "+25% splash radius.", "mod": ("splash_mult", 0.25)},
    {"id": "coreheal", "name": "Hull Plating", "rarity": "common",
     "desc": "Restore & raise core integrity by 25.", "mod": ("core_hp_add", 25)},
    {"id": "discount", "name": "Mass Production", "rarity": "uncommon",
     "desc": "-15% tower build cost.", "mod": ("cost_mult", -0.15)},
    {"id": "dmg2", "name": "Resonance Core", "rarity": "rare",
     "desc": "+30% global tower damage.", "mod": ("dmg_mult", 0.30)},
    {"id": "firstkill", "name": "Bounty Protocol", "rarity": "uncommon",
     "desc": "+1 core HP per 6 kills... wait, +35 money each wave start.",
     "mod": ("wave_income", 35)},
    {"id": "exec", "name": "Executioner", "rarity": "rare",
     "desc": "Instantly kill non-boss enemies below 8% HP.", "mod": ("execute_pct", 0.08)},
    {"id": "dot_plus", "name": "Virulence", "rarity": "uncommon",
     "desc": "+40% damage-over-time.", "mod": ("dot_mult", 0.40)},
    {"id": "overkill", "name": "Spillover", "rarity": "rare",
     "desc": "Overkill damage chains to nearest enemy.", "mod": ("spillover", 1)},
]
