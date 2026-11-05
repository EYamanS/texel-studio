"""Color helpers: hex parsing, tone shifting, ramps and palette extraction. Pure Python + Pillow."""

import colorsys

from PIL import Image


def norm_hex(value: str) -> str:
    """Normalise '#abc', '#aabbcc' or '#aabbccdd' (with alpha) to lowercase long form."""
    h = value.strip().lower()
    if len(h) in (4, 5):
        h = "#" + "".join(ch * 2 for ch in h[1:])
    return h


def to_rgb(value: str) -> tuple[int, int, int]:
    h = norm_hex(value)
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def to_alpha(value: str) -> int:
    """Alpha (0-255) of a '#rrggbbaa' color, 255 for plain '#rrggbb'."""
    h = norm_hex(value)
    return int(h[7:9], 16) if len(h) == 9 else 255


def to_hex(r: float, g: float, b: float) -> str:
    clamp = lambda v: max(0, min(255, round(v)))
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


def luminance(value: str) -> float:
    r, g, b = to_rgb(value)
    return 0.299 * r + 0.587 * g + 0.114 * b


def lightness(value: str) -> float:
    r, g, b = [v / 255 for v in to_rgb(value)]
    return colorsys.rgb_to_hls(r, g, b)[1]


def tone(value: str, d_light: float = 0.0, hue: float = 0.0, sat: float = 1.0) -> str:
    """Shift a color: d_light = lightness delta (-1..1), hue = degrees (+ warmer for lights, - cooler for shadows)."""
    r, g, b = [v / 255 for v in to_rgb(value)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    rr, gg, bb = colorsys.hls_to_rgb((h + hue / 360.0) % 1.0, max(0.0, min(1.0, l + d_light)),
                                     max(0.0, min(1.0, s * sat)))
    return to_hex(rr * 255, gg * 255, bb * 255)


def shift_color(value: str, hue: float = 0.0, sat: float = 1.0, light: float = 0.0) -> str:
    """Whole-color shift used by `variant` (hue in degrees, sat multiplier, light delta). Keeps alpha."""
    h = norm_hex(value)
    out = tone(h[:7], light, hue, sat)
    return out + (h[7:] if len(h) == 9 else "")


def make_ramp(base: str, steps: int = 5, hue_shift: float = 0.04) -> list[str]:
    """Dark -> light ramp around `base`: shadows lean cool, highlights lean warm (classic pixel-art rule)."""
    r, g, b = [v / 255 for v in to_rgb(base)]
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    out = []
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 0.5
        light = 0.14 + 0.76 * t
        direction = -1 if 0.55 < h < 0.8 else 1            # blues/purples shift the other way
        hue = (h + direction * (t - 0.5) * hue_shift) % 1.0
        sat = min(1.0, s * (0.75 + 0.5 * (1 - abs(t - 0.45) * 1.4)))
        rr, gg, bb = colorsys.hls_to_rgb(hue, light, sat)
        out.append(to_hex(rr * 255, gg * 255, bb * 255))
    return out


def palette_from_image(path: str, colors: int = 12) -> list[str]:
    """Quantise an image to `colors` hex colors, sorted dark -> light."""
    im = Image.open(path).convert("RGBA")
    flat = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
    q = flat.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: colors * 3]
    out = ["#%02x%02x%02x" % tuple(pal[i:i + 3]) for i in range(0, len(pal), 3)]
    out.sort(key=lambda h: sum(to_rgb(h)))
    return out
