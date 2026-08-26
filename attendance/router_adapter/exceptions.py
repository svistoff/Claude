class RouterAdapterError(Exception):
    """Базовая ошибка адаптера роутера."""


class RouterUnreachableError(RouterAdapterError):
    """Роутер недоступен по сети (таймаут, connection refused, DNS и т.п.)."""


class RouterAuthError(RouterAdapterError):
    """Логин/пароль не подошли, либо сессия/токен не приняты роутером."""


class RouterResponseError(RouterAdapterError):
    """Роутер ответил, но в неожиданном формате (не тот JSON/HTTP-код)."""
