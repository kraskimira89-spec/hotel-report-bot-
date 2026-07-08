"""FastAPI-приложение: авторизация, дашборд, история, логи, dry-run."""

from __future__ import annotations

import logging
import secrets
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from src.config import get_config, get_env_settings, reload_config
from src.config_runtime import persist_dry_run_to_yaml, save_runtime_overrides
from src.notifiers.email_sender import send_weekly_report
from src.notifiers.max_bot import send_daily_summary
from src.storage.db import get_report_log, init_db
from src.web import queries

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="hotel-report-bot Admin", version="0.2.0")
app.add_middleware(SessionMiddleware, secret_key=get_env_settings().secret_key)


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Редирект на HTTPS в проде (за reverse proxy)."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if get_env_settings().web_force_https:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto != "https":
                url = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
        return await call_next(request)


app.add_middleware(HttpsRedirectMiddleware)


def _is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False) is True


def _require_auth(request: Request) -> RedirectResponse | None:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return None


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
    redirect = _require_auth(request)
    if redirect:
        return redirect
    cfg = get_config()
    data = queries.fetch_dashboard_data()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "config": cfg, "page": "dashboard", "data": data},
    )


@app.get("/snapshots", response_class=HTMLResponse)
async def snapshots_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    rows = queries.fetch_snapshot_rows()
    chart = queries.fetch_snapshot_chart()
    return templates.TemplateResponse(
        request,
        "snapshots.html",
        {"request": request, "snapshots": rows, "chart": chart, "page": "snapshots"},
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    rows = queries.fetch_metrics_rows()
    weekly = queries.fetch_weekly_metrics()
    comparison = queries.fetch_metrics_comparison()
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {
            "request": request,
            "metrics": rows,
            "weekly": weekly,
            "comparison": comparison,
            "page": "metrics",
        },
    )


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    cfg = get_config()
    aggregates = queries.fetch_channel_aggregates()
    return templates.TemplateResponse(
        request,
        "channels.html",
        {
            "request": request,
            "aggregates": aggregates,
            "channels_map": cfg.channels_map,
            "page": "channels",
        },
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    bundle = queries.fetch_logs_bundle()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"request": request, "bundle": bundle, "page": "logs"},
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import get_reports_log

    reports = get_reports_log(limit=50)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "reports": reports, "page": "reports", "message": None},
    )


@app.post("/reports/{report_id}/resend")
async def resend_report(request: Request, report_id: int) -> RedirectResponse:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    record = get_report_log(report_id)
    if record is None:
        return RedirectResponse(url="/reports", status_code=status.HTTP_302_FOUND)

    try:
        if record.report_type == "max":
            send_daily_summary(
                report_date=record.report_date,
                run_date=date.today(),
            )
        elif record.report_type == "email":
            send_weekly_report(
                report_date=record.report_date,
                run_date=date.today(),
                period_start=record.period_start,
                period_end=record.period_end,
            )
    except Exception as exc:
        logger.exception("Повторная отправка отчёта %s: %s", report_id, exc)

    return RedirectResponse(url="/reports", status_code=status.HTTP_302_FOUND)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    cfg = get_config()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"request": request, "config": cfg, "page": "settings", "saved": False},
    )


@app.post("/settings/dry-run")
async def toggle_dry_run(
    request: Request,
    dry_run: str = Form(...),
) -> RedirectResponse:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    value = dry_run.lower() in {"true", "1", "on", "yes"}
    save_runtime_overrides({"dry_run": value})
    persist_dry_run_to_yaml(value)
    reload_config()
    logger.info("dry_run переключён на %s (runtime_settings)", value)
    return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)


@app.post("/settings/save")
async def save_settings(
    request: Request,
    occupancy_green_min: float = Form(...),
    occupancy_yellow_min: float = Form(...),
    price_change_yellow_pct: float = Form(...),
    price_change_red_pct: float = Form(...),
    new_bookings_green_min: int = Form(...),
    new_bookings_yellow_min: int = Form(...),
    price_snapshot_cron: str = Form(...),
    daily_summary_cron: str = Form(...),
    weekly_email_cron: str = Form(...),
    request_delay_min_sec: float = Form(...),
    request_delay_max_sec: float = Form(...),
    max_retries: int = Form(...),
) -> RedirectResponse:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    save_runtime_overrides(
        {
            "traffic_light": {
                "occupancy_green_min": occupancy_green_min,
                "occupancy_yellow_min": occupancy_yellow_min,
                "price_change_yellow_pct": price_change_yellow_pct,
                "price_change_red_pct": price_change_red_pct,
                "new_bookings_green_min": new_bookings_green_min,
                "new_bookings_yellow_min": new_bookings_yellow_min,
            },
            "scheduler": {
                "price_snapshot_cron": price_snapshot_cron,
                "daily_summary_cron": daily_summary_cron,
                "weekly_email_cron": weekly_email_cron,
            },
            "site_prices": {
                "request_delay_min_sec": request_delay_min_sec,
                "request_delay_max_sec": request_delay_max_sec,
                "max_retries": max_retries,
            },
        }
    )
    reload_config()
    return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)
