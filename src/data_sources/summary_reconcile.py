"""Сверка ежедневной сводки с TravelLine «Доходность и загрузка»."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config import AppConfig, get_config, get_db_path
from src.data_sources.travelline import (
    TravelLineClient,
    TravelLineError,
    run_daily_reconciliation,
)
from src.notifiers.max_bot import prepare_daily_summary_data
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord

logger = logging.getLogger(__name__)


@dataclass
class MetricCompare:
    name: str
    summary: float | int | None
    travelline: float | int | None
    unit: str = ""
    ok: bool = True
    note: str = ""


def reconcile_output_dir(config: AppConfig | None = None) -> Path:
    _ = config
    base = get_db_path().parent / "reconcile"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _pct_diff(a: float, b: float) -> float:
    if b == 0:
        return 0.0 if a == 0 else 100.0
    return abs(a - b) / abs(b) * 100.0


def _compare_float(
    name: str,
    summary_val: float | None,
    tl_val: float | None,
    *,
    unit: str = "",
    tol_pct: float = 1.0,
    tol_abs: float = 0.0,
) -> MetricCompare:
    if summary_val is None or tl_val is None:
        return MetricCompare(
            name=name,
            summary=summary_val,
            travelline=tl_val,
            unit=unit,
            ok=False,
            note="нет данных с одной из сторон",
        )
    diff = abs(summary_val - tl_val)
    ok = diff <= tol_abs or _pct_diff(summary_val, tl_val) <= tol_pct
    note = f"Δ={diff:.2f}{unit}"
    if not ok:
        note += f" (> порога {tol_pct}% или {tol_abs}{unit})"
    return MetricCompare(
        name=name,
        summary=round(summary_val, 2),
        travelline=round(tl_val, 2),
        unit=unit,
        ok=ok,
        note=note,
    )


def _compare_int(name: str, summary_val: int, tl_val: int) -> MetricCompare:
    ok = summary_val == tl_val
    note = "совпадает" if ok else f"Δ={summary_val - tl_val:+d}"
    return MetricCompare(
        name=name,
        summary=summary_val,
        travelline=tl_val,
        unit="шт",
        ok=ok,
        note=note,
    )


def build_summary_travelline_reconcile(
    report_date: date,
    *,
    config: AppConfig | None = None,
    client: TravelLineClient | None = None,
) -> dict:
    """Сравнить сводку и прямой запрос TravelLine за дату."""
    cfg = config or get_config()
    summary = prepare_daily_summary_data(report_date, config=cfg)
    tl = client or TravelLineClient(cfg)

    occ = tl.get_stay_occupancy(report_date)
    channels = tl.get_channels(report_date, report_date)
    tl_bookings = sum(int(ch.get("count") or 0) for ch in channels)
    reservations = tl.get_reservations(
        report_date, report_date, date_kind=2, fetch_details=False
    )
    tl_res_count = len(reservations)

    sold = int(occ.sold)
    available = int(occ.available or cfg.property.total_units)
    metrics = tl.get_revenue_metrics(
        report_date,
        report_date,
        sold_unit_nights=sold,
        available_unit_nights=available,
        date_kind=1,
    )

    comparisons: list[MetricCompare] = [
        _compare_float(
            "Загрузка, %",
            summary.occupancy_pct,
            occ.occupancy_pct,
            unit="%",
            tol_pct=1.0,
            tol_abs=0.5,
        ),
        _compare_int("Занято номеров", sold, sold),
        _compare_int(
            "Новые брони (сводка vs get_channels)",
            summary.new_bookings_total,
            tl_bookings,
        ),
        _compare_int(
            "Новые брони (get_reservations dateKind=2)",
            summary.new_bookings_total,
            tl_res_count,
        ),
    ]

    if summary.revenue is not None:
        comparisons.append(
            _compare_float(
                "Выручка за день, ₽",
                summary.revenue,
                float(metrics.get("revenue") or 0),
                unit="₽",
                tol_pct=2.0,
                tol_abs=500.0,
            )
        )

    sheets_warnings = run_daily_reconciliation(report_date, client=tl, config=cfg)
    all_ok = all(c.ok for c in comparisons) and not sheets_warnings

    return {
        "report_date": report_date.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": cfg.dry_run,
        "summary_sources": {
            "occupancy": summary.occupancy_source,
            "bookings": summary.bookings_source,
        },
        "travelline_raw": {
            "occupancy_pct": round(occ.occupancy_pct, 2),
            "sold": sold,
            "available": available,
            "bookings_channels": tl_bookings,
            "bookings_reservations": tl_res_count,
            "revenue": metrics.get("revenue"),
            "adr": metrics.get("adr"),
            "revpar": metrics.get("revpar"),
            "channels": channels,
        },
        "summary_snapshot": {
            "occupancy_pct": round(summary.occupancy_pct, 2),
            "new_bookings_total": summary.new_bookings_total,
            "revenue": summary.revenue,
            "occupancy_source": summary.occupancy_source,
            "bookings_source": summary.bookings_source,
            "warnings": summary.warnings,
        },
        "comparisons": [asdict(c) for c in comparisons],
        "sheets_reconcile_warnings": [w.message for w in sheets_warnings],
        "all_ok": all_ok,
    }


def save_reconcile_report(data: dict, *, output_dir: Path | None = None) -> Path:
    out_dir = output_dir or reconcile_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_date = data.get("report_date", date.today().isoformat())
    path = out_dir / f"reconcile_{report_date}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def prune_reconcile_reports(output_dir: Path | None = None, keep_days: int = 90) -> int:
    out_dir = output_dir or reconcile_output_dir()
    if not out_dir.exists():
        return 0
    cutoff = date.today() - timedelta(days=keep_days)
    removed = 0
    for path in out_dir.glob("reconcile_*.json"):
        try:
            day_str = path.stem.replace("reconcile_", "")
            if date.fromisoformat(day_str) < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except ValueError:
            continue
    return removed


def run_summary_travelline_reconcile(
    report_date: date,
    *,
    config: AppConfig | None = None,
    save: bool = True,
    log_mismatch: bool = True,
) -> dict:
    """Сверка + сохранение JSON; при расхождении — запись в errors_log."""
    data = build_summary_travelline_reconcile(report_date, config=config)
    path: Path | None = None
    if save:
        path = save_reconcile_report(data)
        prune_reconcile_reports()
        logger.info(
            "Сверка сводки/TL за %s: all_ok=%s, файл=%s",
            report_date,
            data["all_ok"],
            path,
        )
    if log_mismatch and not data["all_ok"]:
        failed = [c for c in data["comparisons"] if not c["ok"]]
        save_error_log(
            ErrorLogRecord(
                error_date=report_date,
                source="travelline",
                error_type="summary_travelline_reconcile",
                message=(
                    f"Расхождение сводки и TravelLine за {report_date:%d.%m.%Y}: "
                    f"{len(failed)} метрик"
                ),
                details=json.dumps(
                    {
                        "failed": failed,
                        "sheets": data["sheets_reconcile_warnings"],
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return data
