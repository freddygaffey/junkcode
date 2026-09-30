#!/usr/bin/env python3
"""
Generate the Lyrebird app icon.

The mark is the bird's tail: two outer plumes that sweep up and curl outward,
with fine barred feathers rising between them. That shape is why the bird is
called a lyrebird, and it doubles as a sound figure - which is the whole product.

Drawn rather than drawn-by-hand so it can be regenerated at any size:

    python build/make-icon.py            # PNG + .icns (macOS) + .ico (Windows)
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "icon"
S = 1024                                   # master size

INK_TOP = (24, 42, 36)                     # eucalypt, lit from above
INK_BOTTOM = (10, 20, 17)
PLUME = (238, 236, 226)                    # warm silver, the tail
BARB = (110, 176, 166)                     # teal, the fine barring
BODY = (201, 123, 60)                      # warm ochre, the bird itself


def bezier(p0, p1, p2, p3, steps=280):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def taper(draw, pts, w_start, w_end, colour):
    """Stroke a path with a width that eases from start to end."""
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        t = i / max(n - 1, 1)
        w = w_start + (w_end - w_start) * (t * t * (3 - 2 * t))    # smoothstep
        r = w / 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)


def rounded_mask(size, radius_ratio=0.2237):
    """Apple's continuous-corner ratio, near enough for a squircle."""
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=int(size * radius_ratio), fill=255)
    return m


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # ground: vertical gradient
    grad = Image.new("RGBA", (1, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.point((0, y), fill=(
            int(INK_TOP[0] + (INK_BOTTOM[0] - INK_TOP[0]) * t),
            int(INK_TOP[1] + (INK_BOTTOM[1] - INK_TOP[1]) * t),
            int(INK_TOP[2] + (INK_BOTTOM[2] - INK_TOP[2]) * t), 255))
    img.paste(grad.resize((S, S)), (0, 0))

    # a faint glow behind the mark, so the tail reads as lit
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([S*0.18, S*0.10, S*0.82, S*0.74],
                                 fill=(46, 96, 88, 92))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(S*0.10)))

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    base = (S * 0.5, S * 0.830)

    # Inner barbs: a fan that opens with the plumes, never wider than them.
    for k in (-1, 1):
        for spread, height in ((0.085, 0.330), (0.165, 0.268)):
            tip = (base[0] + k * S * spread, S * height)
            pts = bezier(base,
                         (base[0] + k * S * spread * 0.20, S * 0.68),
                         (tip[0] - k * S * 0.035, tip[1] + S * 0.120),
                         tip, 200)
            taper(d, pts, S * 0.015, S * 0.004, BARB)

    # Outer plumes: an OPEN lyre. They must flare outward at the top - if the
    # tips converge the silhouette closes into an egg and reads as a beetle.
    for k in (-1, 1):
        stem = bezier(base,
                      (base[0] + k * S * 0.150, S * 0.740),
                      (base[0] + k * S * 0.330, S * 0.430),
                      (base[0] + k * S * 0.340, S * 0.215),
                      320)
        taper(d, stem, S * 0.056, S * 0.030, PLUME)

        # The hook: outward and over, the shape that names the bird.
        tip = stem[-1]
        curl = bezier(tip,
                      (tip[0] + k * S * 0.020, S * 0.120),
                      (tip[0] - k * S * 0.090, S * 0.105),
                      (tip[0] - k * S * 0.105, S * 0.192),
                      220)
        taper(d, curl, S * 0.030, S * 0.011, PLUME)

    img = Image.alpha_composite(img, layer)
    img.putalpha(rounded_mask(S))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = build()
    png = OUT / "icon.png"
    icon.save(png)
    print(f"  wrote {png.relative_to(ROOT)}  ({icon.size[0]}px)")

    # Windows .ico
    ico = OUT / "icon.ico"
    icon.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"  wrote {ico.relative_to(ROOT)}")

    # macOS .icns
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT / "icon.iconset"
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir()
        for size in (16, 32, 64, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size*2, size*2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        icns = OUT / "icon.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
        shutil.rmtree(iconset, ignore_errors=True)
        print(f"  wrote {icns.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
