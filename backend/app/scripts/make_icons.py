"""Иконки приложения (PWA) в стиле AI Coder — пергамент + clay.

Рисуем один раз в большом размере и уменьшаем. Пересоздать:
    cd backend && .venv/bin/python -m app.scripts.make_icons
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[3] / "frontend" / "icons"

BG = (240, 238, 230, 255)       # --bg (пергамент)
INK = (20, 20, 19, 255)         # --inversion
CLAY = (217, 119, 87, 255)      # --accent
MUTED = (135, 134, 127, 255)    # --muted

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG if not maskable else CLAY)
    d = ImageDraw.Draw(img)

    # Отступ: у maskable-иконки система обрезает края — держим знак в безопасной зоне.
    margin = int(size * (0.22 if maskable else 0.13))
    plate = size - margin * 2

    if maskable:
        # На цветном фоне — светлая плашка, чтобы знак читался.
        plate_color = BG
    else:
        plate_color = INK

    radius = int(plate * 0.28)
    d.rounded_rectangle([margin, margin, margin + plate, margin + plate],
                        radius=radius, fill=plate_color)

    # Знак «приглашение терминала»: › и _ (агент ждёт задачу). Рисуем линиями,
    # а не глифом: форма не зависит от того, какие шрифты есть на сервере.
    stroke = max(3, int(plate * 0.085))
    cx = margin + plate * 0.30
    cy = margin + plate * 0.50
    arm = plate * 0.17
    fg = INK if maskable else BG
    d.line([(cx, cy - arm), (cx + arm, cy)], fill=fg, width=stroke)
    d.line([(cx + arm, cy), (cx, cy + arm)], fill=fg, width=stroke)
    # Подчёркивание-курсор (акцентный цвет) правее и ниже.
    bx = cx + arm * 1.45
    by = cy + arm * 0.72
    bw = plate * 0.24
    d.rounded_rectangle([bx, by, bx + bw, by + stroke], radius=stroke // 2,
                        fill=CLAY if not maskable else INK)
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {
        "icon-192.png": (draw_icon(512), 192),
        "icon-512.png": (draw_icon(1024), 512),
        "icon-maskable-512.png": (draw_icon(1024, maskable=True), 512),
        "apple-touch-icon-180.png": (draw_icon(512), 180),
        "favicon-32.png": (draw_icon(256), 32),
    }
    for name, (img, size) in targets.items():
        out = OUT_DIR / name
        img.resize((size, size), Image.LANCZOS).save(out, "PNG", optimize=True)
        print("готово:", out.relative_to(OUT_DIR.parent.parent), f"({size}×{size})")

    # favicon.ico — из того же знака
    ico = draw_icon(256).resize((64, 64), Image.LANCZOS)
    ico.save(OUT_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("готово: frontend/icons/favicon.ico")


if __name__ == "__main__":
    main()
