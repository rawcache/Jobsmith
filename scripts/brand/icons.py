"""Draw the extension's icons from the pixel hammer mark (the grid in extension/content.js), in the brand's rust.

    uv run python scripts/brand/icons.py        # writes extension/icons/{16,32,48,128}.png

The mark is drawn in paper on a rounded rust tile. Each size is drawn large and scaled down, so the small ones
stay smooth; the cell size is a whole number of pixels where it can be, so the large ones stay sharp."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
RUST, PAPER = (0x9A, 0x34, 0x12), (0xFB, 0xFA, 0xF8)


def mark() -> list[str]:
    js = (ROOT / "extension/content.js").read_text()
    rows = re.search(r"const MARK = \[(.*?)\];", js, re.S).group(1)
    return re.findall(r'"([.#]+)"', rows)


def icon(size: int, grid: list[str], scale: int = 8) -> Image.Image:
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.22), fill=RUST)
    cols, rows = len(grid[0]), len(grid)
    cell = big * 0.74 / cols
    x0, y0 = (big - cell * cols) / 2, (big - cell * rows) / 2 + cell * 0.3
    for y, row in enumerate(grid):
        for x, c in enumerate(row):
            if c == "#":
                d.rectangle((x0 + x * cell, y0 + y * cell, x0 + (x + 1) * cell - 1, y0 + (y + 1) * cell - 1), fill=PAPER)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    g = mark()
    for s in (16, 32, 48, 128):
        icon(s, g).save(ROOT / f"extension/icons/{s}.png", optimize=True)
        print(f"extension/icons/{s}.png")
