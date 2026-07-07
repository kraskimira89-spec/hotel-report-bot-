"""FastAPI-приложение: авторизация, дашборд, история, логи, dry-run."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from src.config import get_config, get_env_settings, reload_config
from src.storage.db import db_session, init_db

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="hotel-report-bot Admin", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=get_env_settings().secret_key)


def _is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False) is True


@app.on_event("startup")
async def startup() -> None:
    init_db()
    logger.info("Веб-админка запущена")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": None},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    cfg = get_config()
    env = get_env_settings()

    valid_user = secrets.compare_digest(username, cfg.web.admin_username)
    if env.admin_token:
        valid_pass = secrets.compare_digest(password, env.admin_token)
    else:
        valid_pass = secrets.compare_digest(password, env.admin_password)

    if valid_user and valid_pass:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": "Неверный логин или пароль"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    cfg = get_config()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "config": cfg, "page": "dashboard"},
    )


@app.get("/snapshots", response_class=HTMLResponse)
async def snapshots_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    rows: list[dict[str, Any]] = []
    with db_session() as conn:
        cur = conn.execute(
            "SELECT * FROM price_snapshots ORDER BY snapshot_date DESC LIMIT 100"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "snapshots.html",
        {"request": request, "snapshots": rows, "page": "snapshots"},
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    rows: list[dict[str, Any]] = []
    with db_session() as conn:
        cur = conn.execute(
            "SELECT * FROM metrics_daily ORDER BY report_date DESC LIMIT 90"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {"request": request, "metrics": rows, "page": "metrics"},
    )


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    cfg = get_config()
    rows: list[dict[str, Any]] = []
    with db_session() as conn:
        cur = conn.execute(
            "SELECT * FROM bookings_daily ORDER BY report_date DESC LIMIT 100"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "channels.html",
        {
            "request": request,
            "bookings": rows,
            "channels_map": cfg.channels_map,
            "page": "channels",
        },
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    errors: list[dict[str, Any]] = []
    with db_session() as conn:
        cur = conn.execute(
            "SELECT * FROM errors_log ORDER BY created_at DESC LIMIT 100"
        )
        errors = [dict(r) for r in cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"request": request, "errors": errors, "page": "logs"},
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    reports: list[dict[str, Any]] = []
    with db_session() as conn:
        cur = conn.execute(
            "SELECT * FROM reports_log ORDER BY created_at DESC LIMIT 50"
        )
        reports = [dict(r) for r in cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "reports": reports, "page": "reports"},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> Response:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    cfg = get_config()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"request": request, "config": cfg, "page": "settings"},
    )


@app.post("/settings/dry-run")
async def toggle_dry_run(
    request: Request,
    dry_run: bool = Form(...),
) -> RedirectResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # TODO: этап 8 — запись dry_run в settings.yaml на диске
    logger.info("dry_run переключён на %s (заглушка — перечитать YAML)", dry_run)
    reload_config()
    return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)
