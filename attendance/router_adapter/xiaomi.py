"""Адаптер для Xiaomi Router AX3000T (RD23) — прошивка MiWiFi.

!!! ВАЖНО — ПРОЧИТАТЬ ПЕРЕД ВВОДОМ В ЭКСПЛУАТАЦИЮ !!!

MiWiFi не имеет официального публичного API. Схема логина и разбора ответа
ниже основана на общеизвестной (многократно реверс-инжиниренной сообществом)
схеме HTTP API MiWiFi, но НЕ проверялась на конкретной прошивке вашего
устройства. Первое включение сервиса рядом с роутером обязано начаться с
прогона `python -m attendance.tools.test_router_connection` (см. README,
раздел "Когда появится доступ к роутеру") — если формат ответа отличается,
править нужно только этот файл, остального сервиса это не касается
(см. интерфейс RouterAdapter в base.py).

Что может отличаться на практике и на что смотреть при отладке:
  1. Путь логина/структура nonce/алгоритм хеширования пароля — см. LOGIN_KEY
     и _build_password_hash() ниже.
  2. Поле с токеном сессии (stok) может лежать в другом месте JSON-ответа.
  3. Эндпоинт списка устройств (`misystem/devicelist`) может возвращать как
     только online-клиентов, так и все известные — поэтому мы дополнительно
     фильтруем по полю `online`, если оно присутствует.
  4. Имя поля с человекочитаемым именем устройства — пробуем oname/name/
     friendlyName по очереди.
"""
from __future__ import annotations

import hashlib
import logging
import random
import time

import httpx

from attendance.router_adapter.base import RouterAdapter, RouterPollResult, SeenDevice
from attendance.router_adapter.exceptions import (
    RouterAuthError,
    RouterResponseError,
    RouterUnreachableError,
)

logger = logging.getLogger(__name__)

# Захардкоженный "публичный" ключ, используемый в большинстве известных
# реализаций логина MiWiFi для хеширования пароля вместе с nonce.
# ТРЕБУЕТ ПРОВЕРКИ на реальном устройстве.
_LOGIN_KEY = "a2ffa5c9be07488bbb04a3a47d3c5f6a"

_LOGIN_PATH = "/cgi-bin/luci/api/xqsystem/login"
_DEVICELIST_PATH_TMPL = "/cgi-bin/luci/;stok={stok}/api/misystem/devicelist"

_REQUEST_TIMEOUT_SECONDS = 10.0


def _build_nonce() -> str:
    # Формат "0_<device_id>_<unix_ts>_<random>" — device_id не проверяется
    # роутером на клиентской стороне, поэтому используем константу.
    return f"0_attendance-service_{int(time.time())}_{random.randint(1000, 9999)}"


def _build_password_hash(password: str, nonce: str) -> str:
    pwd_key = hashlib.sha1((password + _LOGIN_KEY).encode()).hexdigest()
    return hashlib.sha1((nonce + pwd_key).encode()).hexdigest()


class XiaomiRouterAdapter(RouterAdapter):
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_connected_devices(self) -> RouterPollResult:
        try:
            stok = await self._login()
            raw_devices = await self._fetch_devicelist(stok)
        except RouterUnreachableError as exc:
            logger.warning("Роутер недоступен: %s", exc)
            return RouterPollResult(success=False, devices=[], error=f"Роутер недоступен: {exc}")
        except RouterAuthError as exc:
            logger.error("Ошибка авторизации на роутере: %s", exc)
            return RouterPollResult(success=False, devices=[], error=f"Ошибка авторизации: {exc}")
        except RouterResponseError as exc:
            logger.error("Неожиданный ответ роутера: %s", exc)
            return RouterPollResult(success=False, devices=[], error=f"Неожиданный ответ роутера: {exc}")
        except Exception as exc:  # noqa: BLE001 — адаптер не имеет права падать
            logger.exception("Непредвиденная ошибка адаптера Xiaomi")
            return RouterPollResult(success=False, devices=[], error=f"Непредвиденная ошибка: {exc}")

        return RouterPollResult(success=True, devices=raw_devices)

    async def _login(self) -> str:
        nonce = _build_nonce()
        password_hash = _build_password_hash(self._password, nonce)
        try:
            resp = await self._client.post(
                self._base_url + _LOGIN_PATH,
                data={
                    "username": self._username,
                    "password": password_hash,
                    "logtype": "2",
                    "nonce": nonce,
                },
            )
        except httpx.RequestError as exc:
            raise RouterUnreachableError(str(exc)) from exc

        if resp.status_code != 200:
            raise RouterResponseError(f"HTTP {resp.status_code} на логине")

        try:
            data = resp.json()
        except ValueError as exc:
            raise RouterResponseError(f"Ответ логина не JSON: {resp.text[:200]!r}") from exc

        code = data.get("code")
        if code not in (0, "0"):
            raise RouterAuthError(f"Логин отклонён роутером (code={code}): {data}")

        stok = data.get("token") or data.get("stok")
        if not stok:
            url_field = data.get("url", "")
            if ";stok=" in url_field:
                stok = url_field.split(";stok=", 1)[1].split("/", 1)[0]
        if not stok:
            raise RouterResponseError(f"Не найден stok в ответе логина: {data}")
        return stok

    async def _fetch_devicelist(self, stok: str) -> list[SeenDevice]:
        path = _DEVICELIST_PATH_TMPL.format(stok=stok)
        try:
            resp = await self._client.get(self._base_url + path)
        except httpx.RequestError as exc:
            raise RouterUnreachableError(str(exc)) from exc

        if resp.status_code == 403:
            raise RouterAuthError("stok отклонён роутером (403)")
        if resp.status_code != 200:
            raise RouterResponseError(f"HTTP {resp.status_code} на devicelist")

        try:
            data = resp.json()
        except ValueError as exc:
            raise RouterResponseError(f"Ответ devicelist не JSON: {resp.text[:200]!r}") from exc

        entries = data.get("list")
        if entries is None:
            raise RouterResponseError(f"В ответе devicelist нет поля 'list': {data}")

        devices: list[SeenDevice] = []
        for entry in entries:
            if "online" in entry and not entry.get("online"):
                continue
            mac = entry.get("mac")
            if not mac:
                continue
            hostname = entry.get("oname") or entry.get("name") or entry.get("friendlyName") or None
            ip = None
            ip_list = entry.get("ip")
            if isinstance(ip_list, list) and ip_list:
                ip = ip_list[0].get("ip")
            elif isinstance(entry.get("ip"), str):
                ip = entry.get("ip")
            devices.append(SeenDevice(mac=mac.upper(), hostname=hostname, ip=ip))
        return devices
