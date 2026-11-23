"""Draw the app icon (a gray flag over a steerpoint marker) and write icon.ico plus the web favicon/logo PNG.

    python tools/make_icon.py        # needs Pillow (dev only; the outputs are committed)
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024                                            # draw large, then shrink for clean edges
BG, POLE, FLAG, FLAG_DARK, MARK = "#18222d", "#e8edf2", "#9aa7b4", "#73808d", "#f2a900"


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=200, fill=BG)
    px, top, bottom = 330, 210, 800                  # flagpole
    d.rounded_rectangle((px - 24, top - 24, px + 24, bottom), radius=24, fill=POLE)
    d.ellipse((px - 46, top - 62, px + 46, top + 30), fill=POLE)
    fl = [(px + 24, top + 10), (800, top + 10), (700, top + 150), (800, top + 290), (px + 24, top + 290)]   # swallow-tail flag
    d.polygon(fl, fill=FLAG)
    d.polygon([(px + 24, top + 150), (700, top + 150), (800, top + 290), (px + 24, top + 290)], fill=FLAG_DARK)
    cx, cy, r = 600, 770, 92                         # steerpoint diamond on the ground
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=MARK)
    d.polygon([(cx, cy - r // 2), (cx + r // 2, cy), (cx, cy + r // 2), (cx - r // 2, cy)], fill=BG)
    d.line([(px - 140, bottom + 4), (px + 140, bottom + 4)], fill=POLE, width=14)
    return im


def main() -> None:
    big = draw()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [big.resize((n, n), Image.LANCZOS) for n in sizes]
    imgs[-1].save(ROOT / "icon.ico", format="ICO", sizes=[(n, n) for n in sizes], append_images=imgs[:-1])
    static = ROOT / "grayflag_dtc" / "static"
    big.resize((256, 256), Image.LANCZOS).save(static / "icon.png")
    big.resize((32, 32), Image.LANCZOS).save(static / "favicon.png")


if __name__ == "__main__":
    main()
