#!/usr/bin/env python3
"""Cursor hook: автокоммит + push после завершения задания агента.

Безопасность:
- не трогает секреты (.env, settings.yaml, ключи, БД);
- push в origin (отключение: CURSOR_AUTO_PUSH=0);
- fail-open (всегда exit 0), чтобы не ломать агента;
- отключение коммита: CURSOR_AUTO_COMMIT=0.
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
_LOG_DIR = _ROOT / "logs"
_LOG_FILE = _LOG_DIR / "post_task_commit.log"

_DENY_NAMES = {
    ".env",
    "settings.yaml",
    "service_account.json",
    "mcp.json",
}
_DENY_SUFFIXES = {".env", ".db", ".pem", ".key", ".p12", ".pfx", ".pptx", ".mp4", ".mov", ".avi"}
_DENY_PARTS = {".venv", "node_modules", "__pycache__", ".git"}
_DENY_PREFIXES = (
    "data/",
    "logs/",
    "config/primeval-rain-",
    "docs/presentations/",
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


def _log(message: str) -> None:
    """Пишет в stderr и logs/post_task_commit.log."""
    line = message.rstrip()
    print(line, file=sys.stderr)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        stamp = datetime.now().isoformat(timespec="seconds")
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass


def _git_add_paths(paths: list[str]) -> list[str]:
    """git add по одному файлу; пропускает проблемные pathspec (Windows + кириллица)."""
    added: list[str] = []
    for path in paths:
        proc = _git("add", "--", path)
        if proc.returncode == 0:
            added.append(path)
            continue
        err = (proc.stderr or proc.stdout or "").strip()
        _log(f"post_task_commit: skip add {path!r}: {err[:120]}")
    return added


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
    if "weekly" in joined or "industry_trends" in joined or "email_sender" in joined:
        return "feat: weekly email v2"
    if "post_task_commit" in joined or "auto_commit" in joined or "hooks.json" in joined:
        return "chore: автокоммит и Cursor hooks"
    if "scheduler" in joined:
        return "feat: обновление планировщика"
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


def _ahead_behind() -> tuple[int, int]:
    proc = _git("rev-list", "--left-right", "--count", "origin/main...HEAD")
    if proc.returncode != 0:
        return -1, -1
    parts = proc.stdout.strip().split()
    if len(parts) != 2:
        return -1, -1
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return -1, -1


def _push_enabled() -> bool:
    return os.environ.get("CURSOR_AUTO_PUSH", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _maybe_push() -> None:
    """Push HEAD to upstream if branch is ahead (Sync Changes)."""
    if not _push_enabled():
        print("post_task_commit: push отключён (CURSOR_AUTO_PUSH=0)", file=sys.stderr)
        return

    behind, ahead = _ahead_behind()
    if ahead <= 0:
        return

    # Не пушим, если remote ушёл вперёд — иначе нужен pull/merge
    if behind > 0:
        print(
            f"post_task_commit: push пропущен — behind={behind}, ahead={ahead}",
            file=sys.stderr,
        )
        return

    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    push = _git("push", "-u", "origin", "HEAD")
    _, ahead2 = _ahead_behind()
    if push.returncode != 0:
        err = (push.stderr or push.stdout or "push failed").strip()
        print(f"post_task_commit: push error: {err}", file=sys.stderr)
        return
    print(f"post_task_commit: pushed {branch} (ahead->{ahead2})")


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
        _log("post_task_commit: отключён (CURSOR_AUTO_COMMIT=0)")
        return 0

    if not (_ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        _log(f"post_task_commit: не git-репозиторий ({_ROOT})")
        return 0

    if _busy():
        _log("post_task_commit: пропуск — идёт merge/rebase")
        return 0

    paths = _porcelain_paths()
    if not paths:
        print("post_task_commit: нечего коммитить")
        _maybe_push()
        return 0

    msg = _commit_message(paths)
    if dry_run:
        print("post_task_commit DRY-RUN:")
        print(msg)
        return 0

    added = _git_add_paths(paths)
    if not added:
        _log("post_task_commit: git add не добавил ни одного файла")
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
    _log(f"post_task_commit: {short} {subject}")
    _maybe_push()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
