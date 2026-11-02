"""Серверная генерация PDF из HTML через Playwright (Chromium).

Отдаёт готовый файл на скачивание — работает на любом устройстве, в отличие от
печати браузера (window.print), которая в мобильных/встроенных браузерах часто
не срабатывает. CSS из static/style.css вшивается в HTML, т.к. у страницы,
загруженной через set_content, нет базового адреса для /static.
"""
from __future__ import annotations

from pathlib import Path

_STYLE_LINK = '<link rel="stylesheet" href="/static/style.css">'
_STYLE_PATH = Path(__file__).resolve().parent / "static" / "style.css"


def inline_styles(html: str) -> str:
    css = _STYLE_PATH.read_text(encoding="utf-8")
    return html.replace(_STYLE_LINK, f"<style>{css}</style>")


async def html_to_pdf(html: str) -> bytes:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(inline_styles(html), wait_until="load")
            return await page.pdf(
                format="A4",
                print_background=True,  # сохранить цвета ячеек
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            await browser.close()
