"""CLI: сгенерировать bcrypt-хэш пароля для ADMIN_PASSWORD_HASH.

Использование:
    python -m app.scripts.hash_password 'ваш-пароль'
"""

from __future__ import annotations

import sys

from ..auth import hash_password


def main() -> int:
    if len(sys.argv) != 2:
        print("Использование: python -m app.scripts.hash_password 'пароль'", file=sys.stderr)
        return 1
    print(hash_password(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
