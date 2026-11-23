"""Generate packaging/ashare.ico: the header logo mark (red rising trend
line on a dark rounded square), sizes 16-256. Requires pillow (build group).

Usage: uv run --group build python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "packaging" / "ashare.ico"

BG = "#0f131c"      # --color-panel
FG = "#ef5350"      # --color-up
RENDER = 1024       # supersample, downscale for anti-aliasing


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = RENDER / 24.0
    # rounded dark square with a small margin
    m = 0.6 * s
    d.rounded_rectangle([m, m, RENDER - m, RENDER - m],
                        radius=5 * s, fill=BG)
    w = 2.4 * s
    d.line([(3 * s, 17 * s), (9 * s, 11 * s), (13 * s, 15 * s), (21 * s, 6 * s)],
           fill=FG, width=int(w), joint="curve")
    d.line([(15 * s, 6 * s), (21 * s, 6 * s), (21 * s, 12 * s)],
           fill=FG, width=int(w), joint="curve")
    # round the stroke caps
    for x, y in [(3, 17), (9, 11), (13, 15), (21, 6), (15, 6), (21, 12)]:
        d.ellipse([x * s - w / 2, y * s - w / 2,
                   x * s + w / 2, y * s + w / 2], fill=FG)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = render(256)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT, format="ICO",
              sizes=[(s, s) for s in sizes],
              append_images=[render(s) for s in sizes[1:]])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
