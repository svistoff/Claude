"""Выбор провайдера сбора под конкретный профиль (раздел 1 ТЗ v2)."""
from __future__ import annotations

from ..config import Settings
from ..models import Profile
from ..providers.base import SearchProvider
from ..providers.browser import BrowserProvider
from ..providers.yandex_api import YandexApiProvider


def build_provider(profile: Profile, settings: Settings) -> SearchProvider:
    """Вернуть провайдер под профиль.

    - ``source='browser'`` -> Playwright (персонализированные профили);
    - иначе -> официальный Yandex Search API (непесонализированные профили).

    Бросает ValueError, если нужный провайдер не настроен, — чтобы сбор упал
    явной ошибкой, а не записал фальшивую позицию.
    """
    if profile.source == "browser":
        if not profile.browser_profile_path:
            raise ValueError(f"У профиля {profile.name!r} не задан browser_profile_path")
        return BrowserProvider(
            profile_path=profile.browser_profile_path,
            device=profile.device,
            proxy=settings.browser_proxy or None,
            captcha_api_key=settings.captcha_api_key or None,
            captcha_provider=settings.captcha_provider or None,
        )

    if not settings.yandex_api_configured:
        raise ValueError(
            "Yandex Search API не настроен (YANDEX_API_FOLDER_ID / YANDEX_API_KEY)"
        )
    return YandexApiProvider(
        folder_id=settings.yandex_api_folder_id,
        api_key=settings.yandex_api_key,
    )
