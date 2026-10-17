"""Make the built-in wallpapers (app/web/wallpapers/). Generated here, so there are no
licences to track. Run from the repo root: .venv/bin/python -m toolchain.wallpapers.make
Needs ffmpeg for the animated one."""

import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[2] / "app" / "web" / "wallpapers"
W, H = 2560, 1440


def grain(im: Image.Image, amount: int, seed: int) -> Image.Image:
    """Fine noise: hides the banding smooth gradients get after compression."""
    rnd = random.Random(seed)
    small = Image.frombytes(
        "L", (W // 2, H // 2), bytes(128 + rnd.randint(-amount, amount) for _ in range(W * H // 4))
    ).resize((W, H))
    return Image.blend(im, Image.merge("RGB", (small, small, small)), 0.035)


def blobs(size, base, spots, blur) -> Image.Image:
    w, h = size
    im = Image.new("RGB", size, base)
    d = ImageDraw.Draw(im)
    for cx, cy, r, color in spots:
        d.ellipse([(cx - r) * w, (cy - r) * h, (cx + r) * w, (cy + r) * h], fill=color)
    return im.filter(ImageFilter.GaussianBlur(blur))


def aurora() -> Image.Image:
    spots = [(0.2, 0.22, 0.26, (66, 44, 160)), (0.8, 0.3, 0.22, (22, 110, 112)),
             (0.58, 0.88, 0.26, (104, 38, 112)), (0.08, 0.92, 0.16, (30, 36, 110))]  # fmt: skip
    small = blobs((640, 360), (12, 12, 19), spots, 70)
    return grain(small.resize((W, H), Image.LANCZOS), 40, 1)


def dusk() -> Image.Image:
    im = Image.new("RGB", (W, H))
    px = im.load()
    top, mid, low = (28, 20, 58), (196, 92, 88), (250, 172, 110)
    for y in range(H):
        t = y / H
        c = [int(top[i] + (mid[i] - top[i]) * min(1, t * 1.6)) for i in range(3)]
        if t > 0.62:
            k = (t - 0.62) / 0.38
            c = [int(c[i] + (low[i] - c[i]) * k) for i in range(3)]
        for x in range(0, W, 8):
            for dx in range(8):
                px[x + dx, y] = tuple(c)
    d = ImageDraw.Draw(im)
    layers = [(0.70, 60, (60, 32, 70)), (0.78, 45, (42, 22, 52)), (0.87, 35, (24, 14, 34))]
    for i, (base, amp, color) in enumerate(layers):
        pts = [(x, H * base + amp * math.sin(x / (420 + 90 * i) + i * 1.7)
                + 0.4 * amp * math.sin(x / 130 + i)) for x in range(0, W + 16, 16)]  # fmt: skip
        d.polygon([(0, H), *pts, (W, H)], fill=color)
    d.ellipse([W * 0.62, H * 0.38, W * 0.62 + 220, H * 0.38 + 220], fill=(255, 214, 160))
    return grain(im.filter(ImageFilter.GaussianBlur(1.2)), 30, 2)


def midnight_grid() -> Image.Image:
    im = blobs((640, 360), (8, 8, 14), [(0.5, 0.62, 0.45, (40, 24, 90))], 60).resize((W, H))
    d = ImageDraw.Draw(im)
    horizon = H * 0.58
    for i in range(-40, 41):
        x0 = W / 2 + i * 70
        d.line([(W / 2 + i * 6, horizon), (x0 + i * 140, H)], fill=(70, 56, 140), width=2)
    for k in range(1, 28):
        y = horizon + (H - horizon) * (k / 27) ** 2.2
        d.line([(0, y), (W, y)], fill=(70, 56, 140), width=2)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).rectangle([0, horizon - 6, W, horizon + 6], fill=(150, 110, 255))
    im = Image.blend(
        im, Image.composite(glow, im, glow.convert("L").filter(ImageFilter.GaussianBlur(30))), 0.6
    )
    return grain(im, 30, 3)


def paper() -> Image.Image:
    spots = [(0.25, 0.3, 0.3, (232, 226, 246)), (0.8, 0.75, 0.32, (222, 238, 236))]
    im = blobs((640, 360), (246, 244, 240), spots, 80).resize((W, H), Image.LANCZOS)
    return grain(im, 60, 4)


def save_still(name: str, im: Image.Image) -> None:
    im.save(OUT / f"{name}.webp", "WEBP", quality=82, method=6)
    poster = im.copy()
    poster.thumbnail((480, 480))
    poster.save(OUT / f"{name}.poster.webp", "WEBP", quality=72)


def drift() -> None:
    """A slow aurora that loops seamlessly: every blob moves on a closed path."""
    fps, seconds, size = 24, 12, (480, 270)
    frames = fps * seconds
    proc = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
         "-vf", "scale=1280:720:flags=lanczos,noise=alls=3:allf=t", "-c:v", "libvpx-vp9",
         "-crf", "38", "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p", "-an",
         str(OUT / "drift.webm")],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    first = None
    for f in range(frames):
        a = 2 * math.pi * f / frames
        spots = [
            (0.3 + 0.12 * math.cos(a), 0.35 + 0.1 * math.sin(a), 0.27, (66, 44, 160)),
            (0.72 + 0.1 * math.sin(a + 1), 0.3 + 0.12 * math.cos(a + 1), 0.22, (22, 110, 112)),
            (0.5 + 0.15 * math.cos(2 * a), 0.84 + 0.06 * math.sin(a), 0.26, (104, 38, 112)),
        ]
        im = blobs(size, (12, 12, 19), spots, 45)
        first = first or im
        proc.stdin.write(im.tobytes())
    proc.stdin.close()
    proc.wait()
    # Full size: it's also the still shown when motion is off.
    poster = first.resize((1280, 720), Image.LANCZOS).filter(ImageFilter.GaussianBlur(2))
    poster.save(OUT / "drift.poster.webp", "WEBP", quality=80)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("aurora", aurora), ("dusk", dusk), ("midnight-grid", midnight_grid),
                     ("paper", paper)):  # fmt: skip
        save_still(name, fn())
        print("made", name)
    drift()
    print("made drift")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:28} {f.stat().st_size // 1024:6} KB")
