"""FastAPI-приложение: авторизация, дашборд, история, логи, dry-run."""

from __future__ import annotations

import logging
import secrets
from datetime import date
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Form, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from src.config import get_config, get_env_settings, reload_config
from src.config_runtime import persist_dry_run_to_yaml, save_runtime_overrides
from src.notifiers.email_sender import send_weekly_report
from src.notifiers.max_bot import send_daily_summary
from src.notifiers.max_webhook import handle_max_webhook, log_webhook_error, verify_webhook_secret
from src.storage.db import get_report_log, init_db
from src.web import queries

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCREENSHOTS_DIR = Path("data/screenshots")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="hotel-report-bot Admin", version="0.2.0")
app.add_middleware(SessionMiddleware, secret_key=get_env_settings().secret_key)


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Редирект на HTTPS в проде (за reverse proxy).

    /health не трогаем — Docker healthcheck ходит по HTTP на 127.0.0.1.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if get_env_settings().web_force_https:
            path = request.url.path
            if path != "/health" and not path.startswith("/health/"):
                proto = request.headers.get("x-forwarded-proto", request.url.scheme)
                if proto != "https":
                    url = str(request.url).replace("http://", "https://", 1)
                    return RedirectResponse(
                        url, status_code=status.HTTP_301_MOVED_PERMANENTLY
                    )
        response = await call_next(request)
        return cast(Response, response)


app.add_middleware(HttpsRedirectMiddleware)


def _is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False) is True


def _require_auth(request: Request) -> RedirectResponse | None:
    if not _is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return None


@app.on_event("startup")
async def startup() -> None:
    from src.utils.logging_setup import setup_logging

    setup_logging()
    init_db()
    from src.data_sources.market_trends import seed_trends_if_empty

    seed_trends_if_empty()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Веб-админка запущена")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/max/webhook")
async def max_webhook(request: Request) -> JSONResponse:
    """Webhook Max Bot API (POST /subscriptions → наш endpoint)."""
    secret = request.headers.get("X-Max-Bot-Api-Secret")
    if not verify_webhook_secret(secret):
        log_webhook_error("Неверный X-Max-Bot-Api-Secret")
        return JSONResponse({"ok": False}, status_code=status.HTTP_403_FORBIDDEN)
    try:
        payload = await request.json()
    except Exception as exc:
        log_webhook_error(f"Некорректный JSON webhook: {exc}")
        return JSONResponse({"ok": False}, status_code=status.HTTP_400_BAD_REQUEST)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False}, status_code=status.HTTP_400_BAD_REQUEST)
    result = handle_max_webhook(payload)
    return JSONResponse(result)


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
    return RedirectResponse(url="/analytics", status_code=status.HTTP_302_FOUND)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_legacy(request: Request) -> Response:
    """Старый дашборд (оставлен по прямой ссылке)."""
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


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    source: str | None = Query(default="all"),
    topic: str | None = Query(default=None),
    period_days: str | None = Query(default=None),
    period_custom: str | None = Query(default=None),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    raw = (period_custom or "").strip() or period_days
    days = queries.normalize_period_days(raw, default=14)
    data = queries.fetch_analytics_bundle(
        source=source,
        topic=topic or None,
        period_days=days,
    )
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {"request": request, "data": data, "page": "analytics"},
    )


@app.post("/analytics/refresh")
async def analytics_refresh(
    request: Request,
    period_days: str = Form(default="14"),
    period_custom: str = Form(default=""),
    source: str = Form(default="all"),
    topic: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.analytics.ai_insights import run_insights_refresh

    raw = period_custom.strip() if period_custom and period_custom.strip() else period_days
    days = queries.normalize_period_days(raw, default=14)
    run_insights_refresh(period_days=days)
    q = f"?source={source}&period_days={days}"
    if topic:
        q += f"&topic={topic}"
    return RedirectResponse(url=f"/analytics{q}", status_code=status.HTTP_302_FOUND)


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


@app.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    data = queries.fetch_competitors_bundle()
    return templates.TemplateResponse(
        request,
        "competitors.html",
        {"request": request, "data": data, "page": "competitors"},
    )


@app.get("/screenshots/{file_path:path}")
async def competitor_screenshot(request: Request, file_path: str) -> Response:
    """Скриншоты виджетов — только для авторизованных."""
    redirect = _require_auth(request)
    if redirect:
        return redirect
    base = SCREENSHOTS_DIR.resolve()
    target = (SCREENSHOTS_DIR / file_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        return RedirectResponse(url="/competitors", status_code=status.HTTP_302_FOUND)
    return FileResponse(target)


@app.get("/trends", response_class=HTMLResponse)
async def trends_page(
    request: Request,
    region: str | None = Query(default=None),
    category: str | None = Query(default=None),
    days: int = Query(default=30, ge=7, le=90),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    if region == "all":
        region = None
    data = queries.fetch_trends_bundle(region=region, category=category or None, days=days)
    return templates.TemplateResponse(
        request,
        "trends.html",
        {"request": request, "data": data, "page": "trends"},
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
