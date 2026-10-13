"""Generates the installer wizard bitmaps (same layout as Lavati Cleaner's installer). Run once; outputs are committed.
Needs Pillow and Windows' Segoe UI fonts."""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = r"C:\Windows\Fonts"
ACCENT, ACCENT_D = (47, 111, 237), (26, 86, 214)   # theme.PRIMARY / PRIMARY_DARK
BG_TOP, BG_BOT = (27, 30, 36), (11, 13, 16)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def vgrad(w, h, a, b):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def logo(size):
    """Blue rounded square with the app's download arrow, drawn at 4x and downsampled."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
    img.paste(vgrad(s, s, (74, 133, 245), ACCENT_D).convert("RGBA"), (0, 0), mask)
    d = ImageDraw.Draw(img)
    cx, w = s / 2, s * 0.14
    d.rounded_rectangle((cx - w / 2, s * 0.20, cx + w / 2, s * 0.52), radius=w / 2, fill="white")
    d.polygon([(cx - s * 0.20, s * 0.50), (cx + s * 0.20, s * 0.50), (cx, s * 0.72)], fill="white")
    d.rounded_rectangle((s * 0.24, s * 0.76, s * 0.76, s * 0.82), radius=s * 0.03, fill="white")
    return img.resize((size, size), Image.LANCZOS)


def centered(d, w, y, text, f, fill):
    d.text(((w - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


def wizard_large(version):
    w, h = 328, 628
    img = vgrad(w, h, BG_TOP, BG_BOT)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 6), fill=ACCENT)
    lg = logo(150)
    img.paste(lg, ((w - 150) // 2, 70), lg)
    centered(d, w, 246, "IDM", font("segoeuib.ttf", 40), (240, 241, 243))
    centered(d, w, 300, "D O W N L O A D E R", font("segoeuisl.ttf", 13), (110, 160, 255))
    f3 = font("segoeui.ttf", 16)
    for i, line in enumerate(("Faster downloads.", "Pause and resume anytime.")):
        centered(d, w, 388 + i * 24, line, f3, (160, 166, 176))
    centered(d, w, 580, f"Version {version}", font("segoeui.ttf", 13), (110, 116, 126))
    img.save(os.path.join(ROOT, "installer", "wizard-large.bmp"))


def wizard_small():
    img = Image.new("RGB", (110, 110), (255, 255, 255))
    lg = logo(84)
    img.paste(lg, (13, 13), lg)
    img.save(os.path.join(ROOT, "installer", "wizard-small.bmp"))


def extension_icons():
    out = os.path.join(ROOT, "browser_extension", "icons")
    os.makedirs(out, exist_ok=True)
    for size in (16, 48, 128):
        logo(size).save(os.path.join(out, f"{size}.png"))


if __name__ == "__main__":
    import re
    version = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "idm", "__init__.py")).read()).group(1)
    wizard_large(version)
    wizard_small()
    extension_icons()
    print("installer bitmaps written")
