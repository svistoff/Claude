"""Изолированная временная БД для тестов — не должна задевать prod .env/данные."""
from __future__ import annotations

import os
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="randomgiveaway-tests-")
os.environ.setdefault("DB_PATH", os.path.join(_tmp_dir, "test.db"))
