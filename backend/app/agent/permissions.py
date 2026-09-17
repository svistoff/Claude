"""Классификация действий агента: allow / confirm / block.

Опасные команды терминала и git push требуют подтверждения пользователя (раздел 10 ТЗ).
Некоторые (mkfs, dd if=, fork bomb) блокируются полностью.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import AppConfig

ALLOW = "allow"
CONFIRM = "confirm"
BLOCK = "block"


@dataclass
class Decision:
    action: str          # allow | confirm | block
    reason: str = ""
    preview: str = ""     # что именно подтверждать (команда), показывается в UI


def _command_preview(name: str, args: dict[str, Any]) -> str:
    if name == "terminal":
        return str(args.get("command", "")).strip()
    if name == "git":
        a = args.get("args", [])
        if isinstance(a, list):
            return "git " + " ".join(str(x) for x in a)
        return f"git {a}"
    return name


def classify(name: str, args: dict[str, Any], config: AppConfig) -> Decision:
    policy = config.terminal_policy

    # Терминал: проверяем blocked/confirm по подстрокам.
    if name == "terminal":
        command = str(args.get("command", ""))
        low = command.lower()
        for pat in policy.blocked:
            if pat.lower() in low or _regexish(pat, command):
                return Decision(BLOCK, f"Команда содержит запрещённый паттерн: {pat}",
                                _command_preview(name, args))
        for pat in policy.confirm:
            if pat.lower() in low:
                return Decision(CONFIRM, f"Потенциально опасная команда ({pat}).",
                                _command_preview(name, args))
        return Decision(ALLOW, preview=_command_preview(name, args))

    # Git: push и деструктивные подкоманды требуют подтверждения.
    if name == "git":
        a = args.get("args", [])
        parts = a if isinstance(a, list) else str(a).split()
        parts_l = [str(p).lower() for p in parts]
        if not parts_l:
            return Decision(ALLOW)
        sub = parts_l[0]
        if sub == "push":
            # Прямой push в main/master — особенно подтверждать (раздел 12 ТЗ).
            to_protected = any(b in parts_l for b in ("main", "master"))
            reason = ("git push в защищённую ветку (main/master)!"
                      if to_protected else "git push отправит изменения в remote.")
            return Decision(CONFIRM, reason, _command_preview(name, args))
        if sub == "reset" and "--hard" in parts_l:
            return Decision(CONFIRM, "git reset --hard уничтожит незакоммиченные изменения.",
                            _command_preview(name, args))
        if sub in ("checkout", "clean") and ("-f" in parts_l or "--force" in parts_l or "-fd" in parts_l):
            return Decision(CONFIRM, "Принудительная git-операция может удалить изменения.",
                            _command_preview(name, args))
        return Decision(ALLOW, preview=_command_preview(name, args))

    # Файловые/поисковые инструменты — разрешены (границы проверяются в самих tools).
    return Decision(ALLOW)


def _regexish(pattern: str, text: str) -> bool:
    """Поддержка спец-паттернов вроде fork bomb, где подстрока ненадёжна."""
    try:
        return re.search(re.escape(pattern), text) is not None
    except re.error:
        return False
