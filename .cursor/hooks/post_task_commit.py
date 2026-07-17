#!/usr/bin/env python3
"""Cursor hook: автокоммит изменений после завершения задания агента.

Безопасность:
- не трогает секреты (.env, settings.yaml, ключи, БД);
- не делает push;
- fail-open (всегда exit 0), чтобы не ломать агента;
- отключение: CURSOR_AUTO_COMMIT=0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

_DENY_NAMES = {
    ".env",
    "settings.yaml",
    "service_account.json",
    "mcp.json",
}
_DENY_SUFFIXES = {".env", ".db", ".pem", ".key", ".p12", ".pfx"}
_DENY_PARTS = {".venv", "node_modules", "__pycache__", ".git"}
_DENY_PREFIXES = (
    "data/",
    "logs/",
    "config/primeval-rain-",
)
_DENY_SUBSTRINGS = (
    "credentials",
    "secret_key",
    "id_rsa",
    "id_ed25519",
)


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _enabled() -> bool:
    return os.environ.get("CURSOR_AUTO_COMMIT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _busy() -> bool:
    git_dir = Path(_git("rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = _ROOT / git_dir
    for name in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if (git_dir / name).exists():
            return True
    return False


def _is_safe(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    if not norm or norm.endswith("/"):
        return False
    p = Path(norm)
    if p.name in _DENY_NAMES:
        return False
    if p.suffix.lower() in _DENY_SUFFIXES:
        return False
    if any(part in _DENY_PARTS for part in p.parts):
        return False
    lower = norm.lower()
    if any(lower.startswith(prefix) for prefix in _DENY_PREFIXES):
        return False
    if any(s in lower for s in _DENY_SUBSTRINGS):
        return False
    return True


def _porcelain_paths() -> list[str]:
    proc = _git("status", "--porcelain", "-uall")
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip().strip('"')
        if _is_safe(entry):
            paths.append(entry)
    return sorted(set(paths))


def _subject(paths: list[str]) -> str:
    joined = " ".join(paths).lower()
    if "src/events" in joined or "events.html" in joined or "events_" in joined:
        return "feat: обновление модуля событий"
    if "forecast" in joined:
        return "feat: обновление прогноза"
    if "pyproject.toml" in joined or "ruff" in joined:
        return "chore: правки линтера и конфигурации"
    if joined.startswith("docs/") or " docs/" in f" {joined}":
        return "docs: обновление документации"
    if "test_" in joined or "tests/" in joined:
        return "test: обновление тестов"
    top = sorted({p.split("/", 1)[0] for p in paths})[:3]
    return f"chore: автокоммит после задачи ({', '.join(top)})"


def _commit_message(paths: list[str]) -> str:
    subject = _subject(paths)
    body_lines = [f"- {p}" for p in paths[:40]]
    if len(paths) > 40:
        body_lines.append(f"- … и ещё {len(paths) - 40} файлов")
    return subject + "\n\n" + "\n".join(body_lines) + "\n"


def main() -> int:
    # stdin от Cursor (JSON) — читаем и игнорируем ошибки
    try:
        raw = sys.stdin.read()
        if raw.strip():
            json.loads(raw)
    except json.JSONDecodeError:
        pass

    dry_run = "--dry-run" in sys.argv
    if not _enabled():
        print("post_task_commit: отключён (CURSOR_AUTO_COMMIT=0)", file=sys.stderr)
        return 0

    if not (_ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("post_task_commit: не git-репозиторий", file=sys.stderr)
        return 0

    if _busy():
        print("post_task_commit: пропуск — идёт merge/rebase", file=sys.stderr)
        return 0

    paths = _porcelain_paths()
    if not paths:
        print("post_task_commit: нечего коммитить")
        return 0

    msg = _commit_message(paths)
    if dry_run:
        print("post_task_commit DRY-RUN:")
        print(msg)
        return 0

    add = _git("add", "--", *paths)
    if add.returncode != 0:
        print(add.stderr or add.stdout, file=sys.stderr)
        return 0

    # Повторная проверка: не закоммитить пустое
    staged = _git("diff", "--cached", "--name-only")
    staged_paths = [p for p in staged.stdout.splitlines() if p.strip()]
    if not staged_paths:
        print("post_task_commit: после фильтра staging пуст")
        return 0

    # Защита от случайно пропущенных секретов в staged
    unsafe = [p for p in staged_paths if not _is_safe(p)]
    if unsafe:
        _git("reset", "HEAD", "--", *unsafe)
        print("post_task_commit: сняты из staging:", ", ".join(unsafe), file=sys.stderr)
        staged_paths = [p for p in staged_paths if p not in unsafe]
        if not staged_paths:
            return 0
        msg = _commit_message(staged_paths)

    # -F + UTF-8: надёжнее кириллицы в Windows, чем git commit -m
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".txt",
        delete=False,
    ) as tmp:
        tmp.write(msg)
        msg_path = tmp.name
    try:
        commit = _git("commit", "-F", msg_path)
    finally:
        try:
            os.unlink(msg_path)
        except OSError:
            pass

    if commit.returncode != 0:
        err = (commit.stderr or commit.stdout or "").strip()
        if err and "nothing to commit" not in err.lower():
            print(err, file=sys.stderr)
        return 0

    short = _git("rev-parse", "--short", "HEAD").stdout.strip()
    subject = re.sub(r"\s+", " ", msg.splitlines()[0]).strip()
    print(f"post_task_commit: {short} {subject}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
