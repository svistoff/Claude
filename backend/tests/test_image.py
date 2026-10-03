"""Тесты инструмента генерации изображений (fal.ai) с мок-HTTP."""

from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.tools import image
from app.tools.base import ToolContext


def _ctx(root: Path) -> ToolContext:
    return ToolContext(project_name="test", project_root=root, config=AppConfig())


class _Resp:
    def __init__(self, status_code=200, json_data=None, content=b"", content_type="image/png"):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.text = ""
        self.headers = {"content-type": content_type}

    def json(self):
        return self._json


class _Client:
    """Мок httpx.Client: первый POST → метаданные, затем GET → байты картинки."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        return _Resp(200, {"images": [{"url": "https://cdn.fal/img.png"}]})

    def get(self, url):
        return _Resp(200, content=b"\x89PNG\r\n\x1a\nfake", content_type="image/png")


def test_no_key_returns_error(monkeypatch, tmp_path):
    monkeypatch.setattr(image, "get_settings", lambda: type("S", (), {"fal_key": "", "workspace_tmp": str(tmp_path)})())
    r = image.generate_image(_ctx(tmp_path), "кот")
    assert not r.ok
    assert "FAL_KEY" in r.content


def test_empty_prompt_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(image, "get_settings",
                        lambda: type("S", (), {"fal_key": "k", "workspace_tmp": str(tmp_path)})())
    r = image.generate_image(_ctx(tmp_path), "   ")
    assert not r.ok
    assert "промпт" in r.content.lower()


def test_success_writes_file_and_returns_url(monkeypatch, tmp_path):
    monkeypatch.setattr(image, "get_settings",
                        lambda: type("S", (), {"fal_key": "k", "workspace_tmp": str(tmp_path)})())
    monkeypatch.setattr(image.httpx, "Client", _Client)
    r = image.generate_image(_ctx(tmp_path), "рыжий кот в шляпе")
    assert r.ok, r.content
    url = r.extra["screenshot_url"]
    assert url.startswith("/api/files/media/")
    media_id = url.rsplit("/", 1)[-1]
    # Файл сохранён в media_dir с этим id.
    saved = list(image.media_dir().glob(media_id + ".*"))
    assert saved and saved[0].read_bytes().startswith(b"\x89PNG")
    assert r.extra["prompt"] == "рыжий кот в шляпе"


def test_fal_http_error_surfaced(monkeypatch, tmp_path):
    class _ErrClient(_Client):
        def post(self, url, headers=None, json=None):
            return _Resp(402, {}, content_type="application/json")

    monkeypatch.setattr(image, "get_settings",
                        lambda: type("S", (), {"fal_key": "k", "workspace_tmp": str(tmp_path)})())
    monkeypatch.setattr(image.httpx, "Client", _ErrClient)
    r = image.generate_image(_ctx(tmp_path), "кот")
    assert not r.ok
    assert "402" in r.content
