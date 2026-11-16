"""Выбор провайдера сбора под конкретный профиль (раздел 1 ТЗ v2)."""
from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..models import Profile
from ..providers.base import SearchProvider
from ..providers.browser import BrowserProvider
from ..providers.yandex_api import DEFAULT_ENDPOINT, YandexApiProvider


def build_provider(profile: Profile, settings: Settings) -> SearchProvider:
    """Вернуть провайдер под профиль.

    - ``source='browser'`` -> Playwright (персонализированные профили);
    - иначе -> официальный Yandex Search API (непесонализированные профили).

    Бросает ValueError, если нужный провайдер не настроен, — чтобы сбор упал
    явной ошибкой, а не записал фальшивую позицию.
    """
    if profile.source == "browser":
        # путь профиля: заданный явно, иначе авто по id внутри profiles_dir
        profile_path = profile.browser_profile_path or str(
            Path(settings.profiles_dir) / f"profile-{profile.id}"
        )
        return BrowserProvider(
            profile_path=profile_path,
            device=profile.device,
            proxy=settings.browser_proxy or None,
            captcha_api_key=settings.captcha_api_key or None,
            captcha_provider=settings.captcha_provider or None,
            headless=settings.browser_headless,
            pace=(settings.browser_pace_min, settings.browser_pace_max),
            nav_timeout_ms=settings.browser_nav_timeout_ms,
            artifacts_dir=settings.artifacts_dir,
            save_html=settings.browser_save_html,
            save_screenshot=settings.browser_save_screenshot,
        )

    if not settings.yandex_api_configured:
        raise ValueError(
            "Yandex Search API не настроен (YANDEX_API_FOLDER_ID / YANDEX_API_KEY)"
        )
    return YandexApiProvider(
        folder_id=settings.yandex_api_folder_id,
        api_key=settings.yandex_api_key,
        endpoint=settings.yandex_api_endpoint or DEFAULT_ENDPOINT,
        region_lr=settings.region_lr,
    )
