"""
Generate PNG brand assets matching the SVG geometry.

Outputs:
- assets/icon.png (256x256)
- assets/logo.png (256x256)
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
    return [(int(round(x * s)), int(round(y * s))) for x, y in points]


def draw_mark(draw: ImageDraw.ImageDraw, s: float) -> None:
    """Draw the Triad-style mark at scale factor ``s`` from a 512px design grid."""
    fill = (17, 17, 17, 255)  # #111

    # Main triangle (from assets/logo.svg)
    draw.polygon(scale_points([(256, 56), (106, 316), (406, 316)], s), fill=fill)
    # Support triangles
    draw.polygon(scale_points([(150, 332), (106, 408), (194, 408)], s), fill=fill)
    draw.polygon(scale_points([(362, 332), (318, 408), (406, 408)], s), fill=fill)

    # Base bars (rounded appearance approximated by simple rectangles at small sizes)
    def rect(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        x1, y1 = int(round(x * s)), int(round(y * s))
        x2, y2 = int(round((x + w) * s)), int(round((y + h) * s))
        return (x1, y1, x2, y2)

    draw.rectangle(rect(88, 426, 336, 22), fill=fill)
    draw.rectangle(rect(118, 456, 276, 22), fill=fill)
    draw.rectangle(rect(148, 486, 216, 18), fill=fill)


def make_png(path: Path, size: int) -> None:
    """Render the mark to a transparent PNG of square ``size``."""
    # Work with a 512 design grid so coordinates match the SVG; scale down.
    scale = size / 512.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_mark(draw, scale)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def main() -> None:
    """Generate icon.png and logo.png at 256x256 in assets directory."""
    make_png(ASSETS / "icon.png", 256)
    make_png(ASSETS / "logo.png", 256)


if __name__ == "__main__":
    main()
