#!/usr/bin/env python3
"""
Generate PNG brand assets matching the SVG geometry.

Outputs (all PNG with transparency):
- assets/icon.png (256x256, dark glyph for light backgrounds)
- assets/icon@2x.png (512x512)
- assets/dark_icon.png (256x256, light glyph for dark backgrounds)
- assets/dark_icon@2x.png (512x512)
- assets/logo.png (256x256, same geometry as icon for simplicity)
- assets/logo@2x.png (512x512)
- assets/dark_logo.png (256x256)
- assets/dark_logo@2x.png (512x512)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def scale_points(
    points: Iterable[tuple[float, float]], s: float
) -> list[tuple[int, int]]:
    """Scale 512-grid points by ``s`` and return integer pixel coords."""
    return [(round(x * s), round(y * s)) for x, y in points]


def draw_mark(
    draw: ImageDraw.ImageDraw, s: float, *, fill: tuple[int, int, int, int]
) -> None:
    """Draw the Triad-style mark at scale factor ``s`` from a 512px design grid."""
    # Main triangle (from assets/logo.svg)
    draw.polygon(scale_points([(256, 56), (106, 316), (406, 316)], s), fill=fill)
    # Support triangles
    draw.polygon(scale_points([(150, 332), (106, 408), (194, 408)], s), fill=fill)
    draw.polygon(scale_points([(362, 332), (318, 408), (406, 408)], s), fill=fill)

    # Base bars (rounded appearance approximated by simple rectangles at small sizes)
    def rect(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        x1, y1 = round(x * s), round(y * s)
        x2, y2 = round((x + w) * s), round((y + h) * s)
        return (x1, y1, x2, y2)

    draw.rectangle(rect(88, 426, 336, 22), fill=fill)
    draw.rectangle(rect(118, 456, 276, 22), fill=fill)
    draw.rectangle(rect(148, 486, 216, 18), fill=fill)


def make_png(path: Path, size: int, *, dark: bool) -> None:
    """
    Render the mark to a transparent PNG of square ``size``.

    - dark=False: draw dark glyph (#111) for light backgrounds
    - dark=True: draw light glyph (#fff) for dark backgrounds
    """
    # Work with a 512 design grid so coordinates match the SVG; scale down.
    scale = size / 512.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (255, 255, 255, 255) if dark else (17, 17, 17, 255)
    draw_mark(draw, scale, fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def main() -> None:
    """Generate brand assets (icon/logo, light/dark, 1x/2x)."""
    # 1x (256)
    make_png(ASSETS / "icon.png", 256, dark=False)
    make_png(ASSETS / "dark_icon.png", 256, dark=True)
    make_png(ASSETS / "logo.png", 256, dark=False)
    make_png(ASSETS / "dark_logo.png", 256, dark=True)
    # 2x (512)
    make_png(ASSETS / "icon@2x.png", 512, dark=False)
    make_png(ASSETS / "dark_icon@2x.png", 512, dark=True)
    make_png(ASSETS / "logo@2x.png", 512, dark=False)
    make_png(ASSETS / "dark_logo@2x.png", 512, dark=True)


if __name__ == "__main__":
    main()
