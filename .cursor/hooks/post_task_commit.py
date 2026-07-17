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
# #region agent log
_DEBUG_LOG = Path(__file__).resolve().parents[3] / "debug-a5fdfa.log"


def _dbg(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    import time

    payload = {
        "sessionId": "a5fdfa",
        "runId": os.environ.get("DEBUG_RUN_ID", "pre-fix"),
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# #endregion

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


def main() -> int:
    # stdin от Cursor (JSON) — читаем и игнорируем ошибки
    try:
        raw = sys.stdin.read()
        if raw.strip():
            json.loads(raw)
    except json.JSONDecodeError:
        pass

    dry_run = "--dry-run" in sys.argv
    # #region agent log
    behind0, ahead0 = _ahead_behind()
    _dbg(
        "H1",
        "post_task_commit.py:main:entry",
        "hook start",
        {
            "root": str(_ROOT),
            "enabled": _enabled(),
            "push_enabled_flag": _push_enabled(),
            "behind": behind0,
            "ahead": ahead0,
            "docstring_says_no_push": "не делает push" in (__doc__ or ""),
        },
    )
    # #endregion
    if not _enabled():
        print("post_task_commit: отключён (CURSOR_AUTO_COMMIT=0)", file=sys.stderr)
        return 0

    if not (_ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("post_task_commit: не git-репозиторий", file=sys.stderr)
        return 0

    if _busy():
        print("post_task_commit: пропуск — идёт merge/rebase", file=sys.stderr)
        # #region agent log
        _dbg("H4", "post_task_commit.py:main:busy", "skipped due to merge/rebase", {})
        # #endregion
        return 0

    paths = _porcelain_paths()
    # #region agent log
    _dbg(
        "H3",
        "post_task_commit.py:main:paths",
        "safe paths for commit",
        {"count": len(paths), "sample": paths[:8]},
    )
    # #endregion
    if not paths:
        print("post_task_commit: нечего коммитить")
        # #region agent log
        behind, ahead = _ahead_behind()
        _dbg(
            "H1",
            "post_task_commit.py:main:nothing",
            "no commit; check if still ahead without push",
            {"behind": behind, "ahead": ahead, "push_attempted": False},
        )
        # #endregion
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

    # #region agent log
    behind1, ahead1 = _ahead_behind()
    _dbg(
        "H1",
        "post_task_commit.py:main:after_commit",
        "commit done; push path status",
        {
            "short": short,
            "behind": behind1,
            "ahead": ahead1,
            "push_attempted": False,
            "reason": "push not implemented in hook yet",
        },
    )
    # #endregion
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

