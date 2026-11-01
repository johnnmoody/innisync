"""Draw InniSync's icon: a click wheel (ring, four control marks, plain centre button) on a light plate, once per
accent colour (the nine Y1 colours and grey). Writes <out>/<accent>.png at 1024 px; build_app.sh turns black.png
into the .icns and bundles the rest so the Dock icon can follow the accent."""
import os
import sys

from PIL import Image, ImageDraw

COLORS = {  # the Y1's body colours (same as ui/src/lib/y1.js) and the grey accent
    "black": "#605f64", "silver": "#adacb1", "blue": "#52c7be", "teal": "#afcec9", "pink": "#ecc4cc",
    "purple": "#f2c2d6", "orange": "#f7a374", "yellow": "#f7c85e", "light_yellow": "#f9ed7d", "grey": "#7c7c82",
}
S = 4 * 1024   # drawn large, then scaled down for smooth edges


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def shade(c, f):
    return tuple(max(0, min(255, round(v * f))) for v in c)


def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = map(ch, c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def icon(hex_color):
    body = rgb(hex_color)
    plate, edge = (246, 246, 244), (214, 214, 210)
    ink = (250, 250, 250) if lum(body) < 0.3 else (70, 70, 74)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = S * 0.09   # the plate sits inside macOS's icon grid margin
    d.rounded_rectangle([m, m, S - m, S - m], radius=S * 0.2, fill=plate, outline=edge, width=int(S * 0.006))
    c, R, r = S / 2, S * 0.32, S * 0.115
    d.ellipse([c - R, c - R, c + R, c + R], fill=body, outline=shade(body, 0.8), width=int(S * 0.008))
    d.ellipse([c - r, c - r, c + r, c + r], fill=plate, outline=shade(body, 0.8), width=int(S * 0.008))
    u = S / 1024   # control marks, on a 1024 grid
    d.rounded_rectangle([c - 70 * u, c - 270 * u, c + 70 * u, c - 236 * u], radius=17 * u, fill=ink)   # menu
    for sgn in (-1, 1):   # previous (left, pointing left) / next (right, pointing right): two triangles each
        for k in (0, 1):
            base = c + sgn * (214 - k * 48) * u
            d.polygon([(base, c - 40 * u), (base, c + 40 * u), (base + sgn * 48 * u, c)], fill=ink)
    y = c + 236 * u   # play / pause
    d.polygon([(c - 62 * u, y - 34 * u), (c - 62 * u, y + 34 * u), (c - 4 * u, y)], fill=ink)
    d.rectangle([c + 14 * u, y - 34 * u, c + 34 * u, y + 34 * u], fill=ink)
    d.rectangle([c + 48 * u, y - 34 * u, c + 68 * u, y + 34 * u], fill=ink)
    return im.resize((1024, 1024), Image.LANCZOS)


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, h in COLORS.items():
        icon(h).save(os.path.join(out, f"{name}.png"))
    print(f"wrote {len(COLORS)} icons to {out}")
