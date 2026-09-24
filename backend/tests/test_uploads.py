"""Тесты загрузки файлов в чат: санитизация, лимиты, инъекция контекста."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import uploads_store


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(uploads_store, "uploads_root", lambda: root)
    return root


def test_sanitize_strips_path():
    assert uploads_store.sanitize_name("../../etc/passwd") == "passwd"
    assert uploads_store.sanitize_name("a b/c;d.txt") == "c_d.txt"


def test_save_text_file(ws: Path):
    info = uploads_store.save_upload("notes.txt", b"hello world")
    assert info["is_text"] is True and info["name"] == "notes.txt"
    saved = ws / info["token"] / "notes.txt"
    assert saved.read_bytes() == b"hello world"


def test_reject_secret_name(ws: Path):
    with pytest.raises(ValueError):
        uploads_store.save_upload(".env", b"SECRET=1")


def test_reject_oversize(ws: Path, monkeypatch):
    from app.config import get_app_config
    monkeypatch.setattr(get_app_config().uploads, "max_file_bytes", 10)
    with pytest.raises(ValueError):
        uploads_store.save_upload("big.txt", b"0123456789ABC")


def test_binary_detection(ws: Path):
    info = uploads_store.save_upload("img.bin", b"\x00\x01\x02binary")
    assert info["is_text"] is False


def test_build_context_inlines_text(ws: Path):
    a = uploads_store.save_upload("log.txt", b"error at line 42")
    ctx = uploads_store.build_attachments_context([{"token": a["token"], "name": a["name"]}])
    assert "log.txt" in ctx and "error at line 42" in ctx


def test_build_context_binary_note(ws: Path):
    a = uploads_store.save_upload("pic.bin", b"\x00\xff\x00data")
    ctx = uploads_store.build_attachments_context([{"token": a["token"], "name": a["name"]}])
    assert "бинарный" in ctx


def test_missing_attachment_skipped(ws: Path):
    ctx = uploads_store.build_attachments_context([{"token": "deadbeef", "name": "x.txt"}])
    assert ctx == ""


def test_png_is_image(ws: Path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    assert uploads_store._is_image(png) is True
    a = uploads_store.save_upload("screenshot.png", png)
    assert a["is_text"] is False
    ctx = uploads_store.build_attachments_context([{"token": a["token"], "name": a["name"]}])
    # без tesseract — помечается как скриншот-изображение (не «бинарный»)
    assert "скриншот" in ctx
