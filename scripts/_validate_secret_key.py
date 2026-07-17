#!/usr/bin/env python3
"""Проверка SECRET_KEY в config/.env (VPS smoke)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import re

from src.config_secrets import validate_secret_key

text = Path("/app/config/.env").read_text(encoding="utf-8")
match = re.search(r"^SECRET_KEY=(.*)$", text, re.M)
if not match:
    print("SECRET_KEY missing", file=sys.stderr)
    raise SystemExit(1)
validate_secret_key(match.group(1))
print("SECRET_KEY ok")
