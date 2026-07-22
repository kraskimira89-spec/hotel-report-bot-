"""Модели данных weekly email v2."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from src.data_sources.market_trends import CompetitorPriceInfo


class MetricsSummary(BaseModel):
    occupancy_pct: float | None = None
    adr: float | None = None
    revpar: float | None = None
    als: float | None = None
    revenue: float | None = None
    bookings_count: int = 0
    is_estimated: bool = False


class OccupancyTypeRow(BaseModel):
    room_type: str
    occupancy_pct: float
    prev_week_pct: float | None = None
    risk_hint: str = ""
    source: str = "travelline"


class ExecutiveSummary(BaseModel):
    headline: str = ""
    main_action: str = ""
    confidence_label: str = "средняя"


class KpiCard(BaseModel):
    label: str
    value: str
    delta: str | None = None
    status: str = "🟡"
    is_estimated: bool = False
    note: str = ""


class ImpactFactor(BaseModel):
    text: str
    source: str


class ForecastDayPoint(BaseModel):
    date: date
    occupancy_pct: float | None = None
    label: str = ""


class ForecastBlock(BaseModel):
    occupancy_range: str = ""
    revenue_range: str = ""
    confidence_label: str = "средняя"
    series: list[ForecastDayPoint] = Field(default_factory=list)
    high_demand_days: list[str] = Field(default_factory=list)
    low_risk_days: list[str] = Field(default_factory=list)
    events_note: str = ""


class RecCard(BaseModel):
    priority: str
    deadline: str
    title: str
    rationale: str
    detail_url: str = ""
    docx_url: str = ""
    has_docx: bool = False


class EventCard(BaseModel):
    date_label: str
    title: str
    note: str = ""


class IndustryTrendCard(BaseModel):
    trend_id: int | None = None
    index: int
    title: str
    region_label: str
    what_happened: str
    why_important: str
    for_1apart: str
    action: str
    source_name: str
    source_url: str
    published_at: date | None = None
    is_leading_trend: bool = False


class MarketPosition(BaseModel):
    competitor_median: float | None = None
    our_price: float | None = None
    position_pct: float | None = None
    position_label: str = ""
    freshness_label: str = ""
    source_label: str = "публичные цены"


class DataQualityBlock(BaseModel):
    lines: list[str] = Field(default_factory=list)
    overall: str = "средняя"


class ReportLinks(BaseModel):
    admin_base_url: str = ""
    forecast_url: str = ""
    recommendations_url: str = ""
    trends_url: str = ""


class WeeklyReportData(BaseModel):
    period_start: date
    period_end: date
    forecast_end: date | None = None
    executive_summary: ExecutiveSummary = Field(default_factory=ExecutiveSummary)
    kpi_cards: list[KpiCard] = Field(default_factory=list)
    occupancy_by_type: list[OccupancyTypeRow] = Field(default_factory=list)
    impact_factors: list[ImpactFactor] = Field(default_factory=list)
    forecast_next_14_days: ForecastBlock = Field(default_factory=ForecastBlock)
    priority_recommendations: list[RecCard] = Field(default_factory=list)
    city_events: list[EventCard] = Field(default_factory=list)
    market_position: MarketPosition = Field(default_factory=MarketPosition)
    industry_trends: list[IndustryTrendCard] = Field(default_factory=list)
    data_quality: DataQualityBlock = Field(default_factory=DataQualityBlock)
    report_links: ReportLinks = Field(default_factory=ReportLinks)
    warnings: list[str] = Field(default_factory=list)
    is_partial: bool = False
    critical_error: bool = False
    # legacy compat
    current_metrics: MetricsSummary | None = None
    prev_week_metrics: MetricsSummary | None = None
    direct_share_pct: float | None = None
    aggregator_share_pct: float | None = None
    returning_guests_pct: float | None = None
    market_trends: list[str] = Field(default_factory=list)
    competitor_prices: list[CompetitorPriceInfo] = Field(default_factory=list)
