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
from src.config_secrets import ensure_production_secret_key
from src.notifiers.email_sender import send_weekly_report
from src.notifiers.max_bot import send_daily_summary
from src.notifiers.max_webhook import handle_max_webhook, log_webhook_error, verify_webhook_secret
from src.storage.db import get_report_log, init_db
from src.utils.dates import format_date_ru, format_period_ru
from src.web import queries

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
SCREENSHOTS_DIR = Path("data/screenshots")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["date_ru"] = format_date_ru
templates.env.filters["period_ru"] = (
    lambda start, end=None: format_period_ru(start, end) if end is not None else format_date_ru(start)
)

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
                host = (request.headers.get("host") or "").split(":")[0].lower()
                if host not in ("localhost", "127.0.0.1"):
                    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
                    if proto != "https":
                        url = str(request.url).replace("http://", "https://", 1)
                        return RedirectResponse(
                            url, status_code=status.HTTP_301_MOVED_PERMANENTLY
                        )
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
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
    ensure_production_secret_key()
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


@app.get("/forecast", response_class=HTMLResponse)
async def forecast_page(
    request: Request,
    horizon_days: int = Query(default=7),
    scenario: str = Query(default="base"),
    room_type: str | None = Query(default=None),
    include_events: str = Query(default="true"),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    show_events = include_events.lower() not in ("false", "0", "no")
    data = queries.fetch_forecast_bundle(
        horizon_days=horizon_days,
        scenario=scenario,
        room_type=room_type or None,
        include_events=show_events,
    )
    return templates.TemplateResponse(
        request,
        "forecast.html",
        {"request": request, "data": data, "page": "forecast"},
    )


@app.post("/forecast/refresh")
async def forecast_refresh(
    request: Request,
    horizon_days: int = Form(default=7),
    scenario: str = Form(default="base"),
    room_type: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.forecast.service import run_forecast_refresh

    run_forecast_refresh(horizons=[horizon_days])
    q = f"?horizon_days={horizon_days}&scenario={scenario}"
    if room_type:
        q += f"&room_type={room_type}"
    return RedirectResponse(url=f"/forecast{q}", status_code=status.HTTP_302_FOUND)


def _forecast_reco_redirect(
    horizon_days: int,
    scenario: str,
    room_type: str,
    *,
    rec_id: int | None = None,
    redirect_to: str = "",
) -> str:
    if redirect_to == "card" and rec_id is not None:
        return f"/forecast/recommendation/{rec_id}"
    q = f"?horizon_days={horizon_days}&scenario={scenario}"
    if room_type:
        q += f"&room_type={room_type}"
    return f"/forecast{q}"


def _actor_name() -> str:
    return get_config().web.admin_username or "admin"


@app.get("/forecast/recommendation/{rec_id}", response_class=HTMLResponse)
async def forecast_recommendation_detail(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    uni_id = queries.resolve_universal_id_for_price(rec_id)
    if uni_id is not None:
        return RedirectResponse(
            url=f"/recommendations/{uni_id}",
            status_code=status.HTTP_302_FOUND,
        )
    # Фолбэк на старую карточку, если sync ещё не создал запись
    from src.storage.db import get_price_recommendation_by_id, mark_recommendation_reviewed

    existing = get_price_recommendation_by_id(rec_id)
    if existing is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    if existing.status == "new":
        mark_recommendation_reviewed(rec_id, _actor_name())
    card = queries.fetch_recommendation_card(rec_id)
    if card is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    return templates.TemplateResponse(
        request,
        "recommendation_detail.html",
        {"card": card, "page": "forecast"},
    )


@app.get("/recommendations", response_class=HTMLResponse)
async def recommendations_page(
    request: Request,
    bucket: str = Query(default="all"),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    data = queries.fetch_recommendations_bundle(bucket=bucket)
    return templates.TemplateResponse(
        request,
        "recommendations.html",
        {"data": data, "page": "recommendations"},
    )


@app.post("/recommendations/refresh")
async def recommendations_refresh(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.recommendations.service import refresh_recommendations_center

    refresh_recommendations_center()
    return RedirectResponse(url="/recommendations", status_code=status.HTTP_302_FOUND)


@app.get("/recommendations/{rec_id}", response_class=HTMLResponse)
async def recommendation_universal_detail(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    card = queries.fetch_universal_recommendation_card(rec_id)
    if card is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    return templates.TemplateResponse(
        request,
        "recommendation_universal_detail.html",
        {"card": card, "page": "recommendations"},
    )


@app.get("/recommendations/{rec_id}/export.docx")
async def recommendation_universal_export(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from urllib.parse import quote

    from src.notifiers.docx_export import (
        build_universal_recommendation_docx,
        universal_docx_filename,
    )

    card = queries.fetch_universal_recommendation_card(rec_id)
    if card is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    payload = build_universal_recommendation_docx(card)
    filename = universal_docx_filename(int(card["id"]), card.get("title") or "rec")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="rec_{rec_id}.docx"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


@app.post("/recommendations/{rec_id}/accept")
async def recommendation_accept(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(rec_id, "accepted")
    logger.info("Центр: рекомендация %s принята (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/recommendations/{rec_id}", status_code=status.HTTP_302_FOUND
    )


@app.post("/recommendations/{rec_id}/defer")
async def recommendation_defer(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(rec_id, "in_progress")
    logger.info("Центр: рекомендация %s в работе (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/recommendations/{rec_id}", status_code=status.HTTP_302_FOUND
    )


@app.post("/recommendations/{rec_id}/reject")
async def recommendation_reject(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(rec_id, "rejected")
    logger.info("Центр: рекомендация %s отклонена (%s)", rec_id, _actor_name())
    return RedirectResponse(url="/recommendations", status_code=status.HTTP_302_FOUND)


@app.post("/recommendations/{rec_id}/complete")
async def recommendation_complete(
    request: Request,
    rec_id: int,
    completion_note: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(
        rec_id,
        "done",
        actor=_actor_name(),
        note=completion_note.strip() or None,
    )
    logger.info("Центр: рекомендация %s выполнена (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/recommendations/{rec_id}", status_code=status.HTTP_302_FOUND
    )


@app.post("/recommendations/{rec_id}/problem")
async def recommendation_problem(
    request: Request,
    rec_id: int,
    note: str = Form(...),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(
        rec_id,
        "in_progress",
        note=f"Проблема: {note.strip()}",
    )
    logger.info("Центр: проблема по %s (%s): %s", rec_id, _actor_name(), note)
    return RedirectResponse(
        url=f"/recommendations/{rec_id}", status_code=status.HTTP_302_FOUND
    )


@app.post("/recommendations/{rec_id}/verify")
async def recommendation_verify(
    request: Request,
    rec_id: int,
    note: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_status

    update_recommendation_status(
        rec_id,
        "done",
        actor=_actor_name(),
        note=f"Проверено: {note.strip()}" if note.strip() else "Проверено",
    )
    logger.info("Центр: проверка %s (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/recommendations/{rec_id}", status_code=status.HTTP_302_FOUND
    )


@app.get("/forecast/recommendation/{rec_id}/export.docx")
async def forecast_recommendation_export_docx(request: Request, rec_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.notifiers.docx_export import (
        build_recommendation_docx,
        recommendation_docx_filename,
    )

    card = queries.fetch_recommendation_card(rec_id)
    if card is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    payload = build_recommendation_docx(card)
    filename = recommendation_docx_filename(
        int(card["decision"]["id"]),
        date.fromisoformat(card["decision"]["target_date"]),
        card["decision"]["room_label"],
    )
    # RFC 5987 для кириллицы в имени файла
    from urllib.parse import quote

    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"rec_{rec_id}.docx\"; "
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers=headers,
    )


@app.post("/forecast/recommendation/{rec_id}/accept")
async def forecast_reco_accept(
    request: Request,
    rec_id: int,
    horizon_days: int = Form(default=7),
    scenario: str = Form(default="base"),
    room_type: str = Form(default=""),
    redirect_to: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_price_recommendation_status

    update_price_recommendation_status(rec_id, "accepted")
    logger.info("Рекомендация %s принята (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=_forecast_reco_redirect(
            horizon_days, scenario, room_type, rec_id=rec_id, redirect_to=redirect_to
        ),
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/reject")
async def forecast_reco_reject(
    request: Request,
    rec_id: int,
    horizon_days: int = Form(default=7),
    scenario: str = Form(default="base"),
    room_type: str = Form(default=""),
    redirect_to: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_price_recommendation_status

    update_price_recommendation_status(rec_id, "rejected")
    logger.info("Рекомендация %s отклонена (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=_forecast_reco_redirect(
            horizon_days, scenario, room_type, rec_id=rec_id, redirect_to=redirect_to
        ),
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/defer")
async def forecast_reco_defer(
    request: Request,
    rec_id: int,
    horizon_days: int = Form(default=7),
    scenario: str = Form(default="base"),
    room_type: str = Form(default=""),
    redirect_to: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_price_recommendation_status

    update_price_recommendation_status(rec_id, "deferred")
    logger.info("Рекомендация %s отложена (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=_forecast_reco_redirect(
            horizon_days, scenario, room_type, rec_id=rec_id, redirect_to=redirect_to
        ),
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/comment")
async def forecast_reco_comment(
    request: Request,
    rec_id: int,
    manager_comment: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import update_recommendation_manager_comment

    update_recommendation_manager_comment(rec_id, manager_comment.strip())
    logger.info("Комментарий к рекомендации %s сохранён (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/forecast/recommendation/{rec_id}",
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/apply")
async def forecast_reco_apply(
    request: Request,
    rec_id: int,
    selected_price: float = Form(...),
    applied_note: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import (
        apply_price_recommendation,
        get_price_recommendation_by_id,
        get_price_snapshots_by_date,
    )

    rec = get_price_recommendation_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    if rec.target_date < date.today():
        return HTMLResponse("Нельзя применить рекомендацию с прошедшей датой", status_code=400)
    if rec.status != "accepted":
        return HTMLResponse("Сначала примите рекомендацию", status_code=400)
    if rec.recommended_price_min is None or rec.recommended_price_max is None:
        return HTMLResponse("Нет допустимого диапазона цены", status_code=400)
    if not (
        rec.recommended_price_min <= selected_price <= rec.recommended_price_max
    ):
        return HTMLResponse("Цена вне рекомендованного диапазона", status_code=400)

    snap = rec.recommendation_snapshot_json or {}
    snap_price = snap.get("current_price", rec.current_price)
    live = {
        s.category: s.price for s in get_price_snapshots_by_date(date.today())
    }.get(rec.room_type)
    if (
        live is not None
        and snap_price is not None
        and abs(float(live) - float(snap_price)) >= 1.0
    ):
        return HTMLResponse(
            "Цена изменилась — нужен повторный расчёт",
            status_code=400,
        )

    apply_price_recommendation(
        rec_id,
        selected_price=selected_price,
        applied_by=_actor_name(),
        applied_note=applied_note.strip() or None,
    )
    logger.info(
        "Рекомендация %s отмечена применённой: %s ₽ (%s)",
        rec_id,
        selected_price,
        _actor_name(),
    )
    return RedirectResponse(
        url=f"/forecast/recommendation/{rec_id}",
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/verify")
async def forecast_reco_verify(
    request: Request,
    rec_id: int,
    verification_result: str = Form(...),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import get_price_recommendation_by_id, verify_price_recommendation

    rec = get_price_recommendation_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    if rec.status != "applied":
        return HTMLResponse("Проверка доступна только после применения", status_code=400)
    verify_price_recommendation(rec_id, verification_result.strip())
    logger.info("Рекомендация %s проверена (%s)", rec_id, _actor_name())
    return RedirectResponse(
        url=f"/forecast/recommendation/{rec_id}",
        status_code=status.HTTP_302_FOUND,
    )


@app.post("/forecast/recommendation/{rec_id}/rollback")
async def forecast_reco_rollback(
    request: Request,
    rec_id: int,
    rollback_reason: str = Form(...),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.storage.db import get_price_recommendation_by_id, rollback_price_recommendation

    rec = get_price_recommendation_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Рекомендация не найдена", status_code=404)
    if rec.status not in ("applied", "verified"):
        return HTMLResponse("Откат недоступен для текущего статуса", status_code=400)
    if not rollback_reason.strip():
        return HTMLResponse("Укажите причину отката", status_code=400)
    rollback_price_recommendation(rec_id, rollback_reason.strip())
    logger.info("Рекомендация %s откат: %s (%s)", rec_id, rollback_reason, _actor_name())
    return RedirectResponse(
        url=f"/forecast/recommendation/{rec_id}",
        status_code=status.HTTP_302_FOUND,
    )


@app.get("/events", response_class=HTMLResponse)
async def events_page(
    request: Request,
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_impact: float | None = Query(default=None),
    event_id: int | None = Query(default=None),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    # Старый формат ?event_id= → отдельная карточка
    if event_id is not None:
        return RedirectResponse(url=f"/events/{event_id}", status_code=status.HTTP_302_FOUND)
    data = queries.fetch_events_bundle(
        status=status,
        category=category,
        min_impact=min_impact,
    )
    return templates.TemplateResponse(
        request,
        "events.html",
        {"request": request, "data": data, "page": "events"},
    )


def _public_events_url(request: Request, days: int) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/events/public?days={days}"


@app.get("/events/print", response_class=HTMLResponse)
async def events_print_page(
    request: Request,
    days: int = Query(default=10, ge=1, le=31),
) -> Response:
    """Гостевая афиша A4 для печати (без авторизации и навигации)."""
    from src.events.poster import build_guest_poster_bundle

    data = build_guest_poster_bundle(
        days=days,
        public_url=_public_events_url(request, days),
    )
    return templates.TemplateResponse(
        request,
        "events_print.html",
        {"request": request, "data": data},
    )


@app.get("/events/public", response_class=HTMLResponse)
async def events_public_page(
    request: Request,
    days: int = Query(default=10, ge=1, le=31),
) -> Response:
    """Мобильная гостевая афиша (QR с печатного листа)."""
    from src.events.poster import build_guest_poster_bundle

    data = build_guest_poster_bundle(
        days=days,
        public_url=_public_events_url(request, days),
    )
    return templates.TemplateResponse(
        request,
        "events_public.html",
        {"request": request, "data": data},
    )


@app.get("/events/{event_id}", response_class=HTMLResponse)
async def events_detail_page(request: Request, event_id: int) -> Response:
    """Подробная карточка события + таблица проверки."""
    redirect = _require_auth(request)
    if redirect:
        return redirect
    data = queries.fetch_events_bundle(event_id=event_id)
    if not data.get("detail"):
        return RedirectResponse(url="/events", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request,
        "events.html",
        {"request": request, "data": data, "page": "events"},
    )


@app.post("/events/refresh")
async def events_refresh(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import run_events_pipeline

    run_events_pipeline(force=True)
    return RedirectResponse(url="/events", status_code=status.HTTP_302_FOUND)


@app.post("/events/create")
async def events_create(
    request: Request,
    title: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(default=""),
    start_time: str = Form(default=""),
    category: str = Form(default="other"),
    venue_name: str = Form(default=""),
    estimated_capacity: int | None = Form(default=None),
    audience_scope: str = Form(default="unknown"),
    description: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import create_manual_event

    end = date.fromisoformat(end_at) if end_at.strip() else None
    create_manual_event(
        title=title.strip(),
        start_at=date.fromisoformat(start_at),
        end_at=end,
        start_time=start_time.strip() or None,
        category=category,
        venue_name=venue_name.strip() or None,
        estimated_capacity=estimated_capacity,
        audience_scope=audience_scope,
        description=description.strip() or None,
    )
    return RedirectResponse(url="/events", status_code=status.HTTP_302_FOUND)


@app.post("/events/{event_id}/approve")
async def events_approve(request: Request, event_id: int, comment: str = Form(default="")) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import approve_event

    approve_event(event_id, comment=comment.strip() or None)
    return RedirectResponse(url=f"/events/{event_id}", status_code=status.HTTP_302_FOUND)


@app.post("/events/{event_id}/reject")
async def events_reject(request: Request, event_id: int, comment: str = Form(default="")) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import reject_event

    reject_event(event_id, comment=comment.strip() or None)
    return RedirectResponse(url=f"/events/{event_id}", status_code=status.HTTP_302_FOUND)


@app.post("/events/{event_id}/cancel")
async def events_cancel(request: Request, event_id: int, comment: str = Form(default="")) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import cancel_event

    cancel_event(event_id, comment=comment.strip() or None)
    return RedirectResponse(url=f"/events/{event_id}", status_code=status.HTTP_302_FOUND)


@app.post("/events/{event_id}/adjust")
async def events_adjust(
    request: Request,
    event_id: int,
    impact_score: float | None = Form(default=None),
    audience_scope: str = Form(default=""),
    category: str = Form(default=""),
    estimated_capacity: int | None = Form(default=None),
    start_at: str = Form(default=""),
    end_at: str = Form(default=""),
    start_time: str = Form(default=""),
    comment: str = Form(default=""),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    from src.events.service import adjust_event

    adjust_event(
        event_id,
        impact_score=impact_score,
        audience_scope=audience_scope.strip() or None,
        category=category.strip() or None,
        estimated_capacity=estimated_capacity,
        start_at=date.fromisoformat(start_at) if start_at.strip() else None,
        end_at=date.fromisoformat(end_at) if end_at.strip() else None,
        start_time=start_time.strip(),
        comment=comment.strip() or None,
    )
    return RedirectResponse(url=f"/events/{event_id}", status_code=status.HTTP_302_FOUND)


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
