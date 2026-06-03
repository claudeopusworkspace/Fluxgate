"""Procedural drawing primitives: glow, neon polygons, gradients.

Everything is generated at runtime from math — radial glow textures come from a
numpy falloff, shapes are computed n-gons, the background is a generated
gradient + grid + starfield. No image files are ever loaded.

Glow textures and gradients are cached by quantized key so per-frame cost stays
low even with many additive blits.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
import pygame

RGB = Tuple[int, int, int]

_glow_cache: Dict[Tuple[int, RGB, int], pygame.Surface] = {}
_grad_cache: Dict[Tuple[int, int, RGB, RGB], pygame.Surface] = {}


def make_glow(radius: int, color: RGB, intensity: float = 1.0) -> pygame.Surface:
    """A radial additive-glow texture (RGB premultiplied by falloff)."""
    radius = max(2, int(radius))
    key = (radius, color, int(intensity * 10))
    cached = _glow_cache.get(key)
    if cached is not None:
        return cached
    size = radius * 2
    ax = np.arange(size)
    xx, yy = np.meshgrid(ax, ax)
    d = np.sqrt((xx - radius) ** 2 + (yy - radius) ** 2) / radius
    falloff = np.clip(1.0 - d, 0.0, 1.0) ** 2 * intensity
    rgb = np.empty((size, size, 3), dtype=np.uint8)
    rgb[..., 0] = np.clip(color[0] * falloff, 0, 255)
    rgb[..., 1] = np.clip(color[1] * falloff, 0, 255)
    rgb[..., 2] = np.clip(color[2] * falloff, 0, 255)
    surf = pygame.Surface((size, size))
    pygame.surfarray.blit_array(surf, rgb)
    _glow_cache[key] = surf
    return surf


def blit_glow(surf: pygame.Surface, pos: Tuple[float, float], radius: int,
              color: RGB, intensity: float = 1.0) -> None:
    g = make_glow(radius, color, intensity)
    r = g.get_width() // 2
    surf.blit(g, (int(pos[0]) - r, int(pos[1]) - r),
              special_flags=pygame.BLEND_RGB_ADD)


def vertical_gradient(w: int, h: int, top: RGB, bottom: RGB) -> pygame.Surface:
    key = (w, h, top, bottom)
    cached = _grad_cache.get(key)
    if cached is not None:
        return cached
    col = np.linspace(0.0, 1.0, h)[:, None]
    arr = np.empty((h, w, 3), dtype=np.uint8)
    for c in range(3):
        arr[..., c] = (top[c] + (bottom[c] - top[c]) * col).astype(np.uint8)
    surf = pygame.Surface((w, h))
    # surfarray expects (w, h, 3); transpose rows/cols
    pygame.surfarray.blit_array(surf, np.transpose(arr, (1, 0, 2)))
    _grad_cache[key] = surf
    return surf


def ngon_points(cx: float, cy: float, radius: float, n: int,
                rotation: float = 0.0) -> List[Tuple[float, float]]:
    pts = []
    for i in range(n):
        a = rotation + i * math.tau / n
        pts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    return pts


def star_points(cx: float, cy: float, outer: float, inner: float, n: int,
                rotation: float = 0.0) -> List[Tuple[float, float]]:
    pts = []
    for i in range(n * 2):
        r = outer if i % 2 == 0 else inner
        a = rotation + i * math.pi / n
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def neon_poly(surf: pygame.Surface, points, fill: RGB, outline: RGB,
              glow_color: RGB, glow_radius: int, width: int = 2,
              glow_intensity: float = 0.9) -> None:
    """Filled polygon with a bright outline and an additive glow halo."""
    if glow_radius > 0:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        blit_glow(surf, (cx, cy), glow_radius, glow_color, glow_intensity)
    pygame.draw.polygon(surf, fill, points)
    pygame.draw.polygon(surf, outline, points, width)


def neon_circle(surf: pygame.Surface, pos, radius: float, fill: RGB,
                outline: RGB, glow_color: RGB, glow_radius: int,
                width: int = 2, glow_intensity: float = 0.9) -> None:
    if glow_radius > 0:
        blit_glow(surf, pos, glow_radius, glow_color, glow_intensity)
    ipos = (int(pos[0]), int(pos[1]))
    pygame.draw.circle(surf, fill, ipos, int(radius))
    if width > 0:
        pygame.draw.circle(surf, outline, ipos, int(radius), width)


def neon_line(surf: pygame.Surface, a, b, color: RGB, width: int,
              glow_color: RGB = None, glow_radius: int = 0) -> None:
    if glow_radius > 0:
        gc = glow_color or color
        steps = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / glow_radius))
        for i in range(steps + 1):
            t = i / steps
            blit_glow(surf, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                      glow_radius, gc, 0.5)
    pygame.draw.line(surf, color, a, b, width)


def jagged_line(a, b, segments: int, jitter: float, rng) -> List[Tuple[float, float]]:
    """A lightning-style polyline between a and b with perpendicular jitter."""
    pts = [a]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    for i in range(1, segments):
        t = i / segments
        off = (rng.random() * 2 - 1) * jitter
        pts.append((a[0] + dx * t + nx * off, a[1] + dy * t + ny * off))
    pts.append(b)
    return pts
