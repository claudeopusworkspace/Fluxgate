"""Procedural neon palette + color math.

No static art anywhere: every colour the game shows is derived from these named
hues and the helper functions (lighten/darken/mix/pulse). Tower and enemy
"color" ids in :mod:`config` map to entries here.
"""

from __future__ import annotations

import colorsys
import math
from typing import Tuple

RGB = Tuple[int, int, int]

# Named neon hues. Chosen for high saturation against a dark field.
HUES: dict[str, RGB] = {
    # towers
    "cyan":     (60, 230, 255),
    "lime":     (150, 255, 90),
    "orange":   (255, 160, 50),
    "ice":      (130, 200, 255),
    "violet":   (190, 120, 255),
    "red":      (255, 80, 90),
    "toxic":    (170, 255, 60),
    "gold":     (255, 215, 90),
    # enemies
    "steel":    (150, 170, 200),
    "yellow":   (255, 230, 80),
    "rust":     (220, 120, 70),
    "pink":     (255, 120, 200),
    "azure":    (90, 170, 255),
    "green":    (90, 255, 150),
    "magenta":  (255, 80, 220),
    "spectral": (180, 220, 255),
    "boss":     (255, 90, 160),
    # misc
    "white":    (255, 255, 255),
    "red_warn": (255, 70, 70),
}

# Background gradient endpoints (deep space blues/purples).
BG_TOP = (10, 12, 26)
BG_BOTTOM = (20, 16, 40)
GRID_COLOR = (40, 48, 80)
PATH_CORE = (70, 90, 140)
PATH_GLOW = (120, 170, 255)


def hue(name: str) -> RGB:
    return HUES.get(name, (255, 255, 255))


def clamp(v: float) -> int:
    return max(0, min(255, int(v)))


def lighten(c: RGB, amt: float) -> RGB:
    return (clamp(c[0] + (255 - c[0]) * amt),
            clamp(c[1] + (255 - c[1]) * amt),
            clamp(c[2] + (255 - c[2]) * amt))


def darken(c: RGB, amt: float) -> RGB:
    return (clamp(c[0] * (1 - amt)), clamp(c[1] * (1 - amt)), clamp(c[2] * (1 - amt)))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return (clamp(a[0] + (b[0] - a[0]) * t),
            clamp(a[1] + (b[1] - a[1]) * t),
            clamp(a[2] + (b[2] - a[2]) * t))


def with_value(c: RGB, value: float) -> RGB:
    """Scale brightness in HSV space, keeping hue/saturation."""
    r, g, b = (x / 255 for x in c)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v = max(0.0, min(1.0, value))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (clamp(r * 255), clamp(g * 255), clamp(b * 255))


def shift_hue(c: RGB, delta: float) -> RGB:
    r, g, b = (x / 255 for x in c)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + delta) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (clamp(r * 255), clamp(g * 255), clamp(b * 255))


def pulse(t: float, lo: float = 0.6, hi: float = 1.0, speed: float = 1.0) -> float:
    """Smooth 0..1 oscillation for breathing glow effects."""
    return lo + (hi - lo) * 0.5 * (1 + math.sin(t * speed * math.tau))


def health_color(frac: float) -> RGB:
    """Green -> yellow -> red as health drops."""
    frac = max(0.0, min(1.0, frac))
    if frac > 0.5:
        return mix((255, 200, 60), (90, 255, 150), (frac - 0.5) * 2)
    return mix((255, 70, 70), (255, 200, 60), frac * 2)
