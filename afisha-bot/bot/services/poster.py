"""Афиша из видео. Если в анонсе есть видео, но нет картинки, берём самый удачный
кадр (резкий, не чёрный и не пересвеченный) и собираем фирменную афишу ЕКБ ГИД:
кадр на весь фон, плашка «ЕКБ ГИД · АФИША», дата/время, название на жёлтом
маркере и площадка. Получается обложка 3:4 — как карточки на сайте и в виджете.

Шрифты (Montserrat Bold, JetBrains Mono Bold, лицензия SIL OFL) лежат в
bot/assets/fonts, видео читается через PyAV (ffmpeg внутри пакета, ставить
ffmpeg в систему не нужно)."""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

import av
from aiogram import Bot
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

logger = logging.getLogger(__name__)

W, H = 1080, 1440
PAD = 72
_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_DISP = str(_FONTS / "Montserrat-Bold.ttf")
_MONO = str(_FONTS / "JetBrainsMono-Bold.ttf")

# дизайн-код ЕКБ ГИД
INK = (25, 21, 18)
PAPER = (244, 241, 233)
CARD = (255, 253, 247)
HL = (245, 226, 75)

_SAMPLES = 9  # сколько кадров рассматриваем


def _score(img: Image.Image) -> float:
    """Чем резче кадр и чем ближе его яркость к нормальной — тем выше оценка."""
    g = ImageOps.grayscale(img.resize((320, int(320 * img.height / max(img.width, 1)))))
    brightness = ImageStat.Stat(g).mean[0]
    edges = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    if brightness < 35 or brightness > 225:  # почти чёрный / белый (затемнения, вспышки)
        return edges * 0.1
    return edges * (1 - abs(brightness - 125) / 250)


def pick_frame(path: str) -> Image.Image | None:
    with av.open(path) as container:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            return None
        duration = None
        if stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        elif container.duration:
            duration = container.duration / av.time_base

        candidates: list[Image.Image] = []
        if duration and duration > 1:
            # 10%..90% длительности: начало и конец часто затемнены
            for i in range(_SAMPLES):
                t = duration * (0.1 + 0.8 * i / (_SAMPLES - 1))
                try:
                    container.seek(int(t / stream.time_base), stream=stream)
                    frame = next(container.decode(stream))
                    candidates.append(frame.to_image())
                except (StopIteration, av.AVError):
                    continue
        if not candidates:  # короткое видео или не вышло перемотать — берём каждый 10-й кадр
            for n, frame in enumerate(container.decode(stream)):
                if n % 10 == 0:
                    candidates.append(frame.to_image())
                if len(candidates) >= _SAMPLES:
                    break
    if not candidates:
        return None
    return max(candidates, key=_score).convert("RGB")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        probe = f"{line} {word}".strip()
        if draw.textlength(probe, font=font) <= width or not line:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_title(draw: ImageDraw.ImageDraw, title: str, width: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Подбираем размер, чтобы название уложилось в 4 строки; длиннее — обрезаем с «…»."""
    for size in (104, 92, 82, 72, 64, 56):
        font = ImageFont.truetype(_DISP, size)
        lines = _wrap(draw, title, font, width)
        if len(lines) <= 4 and all(draw.textlength(l, font=font) <= width for l in lines):
            return font, lines
    lines = lines[:4]
    while lines and draw.textlength(lines[-1] + "…", font=font) > width:
        lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
    lines[-1] += "…"
    return font, lines


def _pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, color, pad=(22, 12)) -> int:
    """Рисует плашку-«таблетку», возвращает её высоту."""
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    w, h = r - l + pad[0] * 2, b - t + pad[1] * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    draw.text((x + pad[0] - l, y + pad[1] - t), text, font=font, fill=color)
    return h


def render_poster(frame: Image.Image, *, title: str, when: str, venue: str | None) -> bytes:
    bg = ImageOps.fit(frame, (W, H), method=Image.LANCZOS, centering=(0.5, 0.4))
    img = bg.convert("RGBA")

    # затемнение снизу вверх — под текстом, чтобы читалось на любом кадре
    shade = Image.new("L", (1, H))
    for yy in range(H):
        k = max(0.0, (yy - H * 0.38) / (H * 0.62))
        shade.putpixel((0, yy), int(235 * min(1.0, k) ** 1.25))
    overlay = Image.new("RGBA", (W, H), INK + (0,))
    overlay.putalpha(shade.resize((W, H)))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    mono_s = ImageFont.truetype(_MONO, 26)
    mono_m = ImageFont.truetype(_MONO, 36)
    _pill(draw, (PAD, PAD), "ЕКБ ГИД · АФИША", mono_s, PAPER, INK, pad=(22, 14))

    width = W - PAD * 2 - 28
    font, lines = _fit_title(draw, title.upper(), width)
    line_h = int(font.size * 1.18)

    venue_font = ImageFont.truetype(_MONO, 32)
    venue_lines = _wrap(draw, venue.upper(), venue_font, W - PAD * 2)[:2] if venue else []

    # раскладка снизу вверх: площадка → название → дата
    y = H - PAD
    if venue_lines:
        y -= len(venue_lines) * 44
        vy = y
        for vl in venue_lines:
            draw.text((PAD, vy), vl, font=venue_font, fill=PAPER)
            vy += 44
        y -= 30
    y -= len(lines) * line_h
    ty = y
    for ln in lines:  # жёлтый маркер под каждой строкой, как .hl на сайте
        l, t, r, b = draw.textbbox((0, 0), ln, font=font)
        draw.rectangle((PAD, ty + int(line_h * 0.08), PAD + (r - l) + 28, ty + line_h - int(line_h * 0.04)), fill=HL)
        draw.text((PAD + 14 - l, ty + (line_h - (b - t)) // 2 - t), ln, font=font, fill=INK)
        ty += line_h
    if when:
        l, t, r, b = draw.textbbox((0, 0), when.upper(), font=mono_m)
        pill_h = b - t + 24  # как pad по вертикали в _pill
        _pill(draw, (PAD, y - 34 - pill_h), when.upper(), mono_m, CARD, INK)

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=88, optimize=True, progressive=True)
    return out.getvalue()


def _build(path: str, title: str, when: str, venue: str | None) -> bytes | None:
    frame = pick_frame(path)
    if frame is None:
        return None
    return render_poster(frame, title=title, when=when, venue=venue)


async def poster_from_video(bot: Bot, file_id: str, *, title: str, when: str, venue: str | None) -> bytes | None:
    """Скачивает видео (Bot API отдаёт до 20 МБ) и собирает афишу. None — если кадр не достать."""
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        await bot.download(file_id, destination=tmp.name)
        return await asyncio.to_thread(_build, tmp.name, title, when, venue)
