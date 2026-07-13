#!/usr/bin/env python3
"""Проверка доступа SA к известным таблицам (без Drive list API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Таблица из config проекта
KNOWN = [
    (
        "1tCPA1HeT5y48zvP3Gj9VG0Gpj9an0BG37Zn1_X69ehQ",
        "Апарт отель для Сергея",
    ),
]


def check_sa(sa_path: str) -> None:
    path = Path(sa_path)
    print(f"=== SA: {sa_path} ===")
    if not path.is_file():
        print("файл не найден\n")
        return
    info = json.loads(path.read_text(encoding="utf-8"))
    print(f"client_email: {info.get('client_email')}")
    print(f"project_id: {info.get('project_id')}")

    creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)
    client = gspread.authorize(creds)

    # попытка list (нужен Drive API)
    try:
        files = client.list_spreadsheet_files()
        print(f"Drive list: доступен, таблиц={len(files)}")
        for item in files:
            print(f"  - {item.get('name')} | {item.get('id')}")
    except APIError as exc:
        print(f"Drive list: недоступен — {exc}")

    print("Проверка известных таблиц:")
    for file_id, expected_title in KNOWN:
        try:
            ss = client.open_by_key(file_id)
            sheets = [f"{ws.title}(gid={ws.id})" for ws in ss.worksheets()]
            print(f"  OK  «{ss.title}» id={ss.id}")
            print(f"      листы: {', '.join(sheets)}")
            if expected_title and ss.title != expected_title:
                print(f"      (ожидали название: {expected_title})")
        except SpreadsheetNotFound:
            print(f"  FAIL «{expected_title}» — не найдена / нет доступа (id={file_id})")
        except APIError as exc:
            print(f"  FAIL «{expected_title}» — {exc}")
    print()


def main() -> int:
    paths = sys.argv[1:] or [
        "config/primeval-rain-407708-566982b64748.json",
        "config/service_account.json",
    ]
    for p in paths:
        check_sa(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
