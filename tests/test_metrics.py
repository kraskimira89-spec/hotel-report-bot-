"""Тесты формул метрик."""

from src.config import TrafficLightThresholds
from src.metrics.occupancy import (
    calc_occupancy,
    traffic_light,
    traffic_light_status,
)
from src.metrics.revenue import (
    DailyMetrics,
    RevenueResult,
    calc_adr,
    calc_als,
    calc_revpar,
    calc_revpar_from_adr_occupancy,
    compute_daily_metrics,
    resolve_revenue,
)


class TestOccupancy:
    def test_normal(self) -> None:
        assert calc_occupancy(30, 44) == 68.18

    def test_full(self) -> None:
        assert calc_occupancy(44, 44) == 100.0

    def test_zero_available(self) -> None:
        assert calc_occupancy(10, 0) == 0.0

    def test_zero_sold(self) -> None:
        assert calc_occupancy(0, 44) == 0.0

    def test_negative_available(self) -> None:
        assert calc_occupancy(5, -1) == 0.0


class TestTrafficLight:
    def setup_method(self) -> None:
        self.th = TrafficLightThresholds()

    def test_occupancy_green(self) -> None:
        assert traffic_light_status(75, self.th, "occupancy") == "green"
        assert traffic_light(75, self.th, "occupancy") == "🟢"

    def test_occupancy_yellow(self) -> None:
        assert traffic_light_status(55, self.th, "occupancy") == "yellow"
        assert traffic_light(55, self.th, "occupancy") == "🟡"

    def test_occupancy_red(self) -> None:
        assert traffic_light_status(30, self.th, "occupancy") == "red"
        assert traffic_light(30, self.th, "occupancy") == "🔴"

    def test_price_change_green(self) -> None:
        assert traffic_light(2, self.th, "price_change") == "🟢"

    def test_price_change_yellow(self) -> None:
        assert traffic_light(7, self.th, "price_change") == "🟡"

    def test_price_change_red(self) -> None:
        assert traffic_light(15, self.th, "price_change") == "🔴"

    def test_new_bookings_green(self) -> None:
        assert traffic_light(5, self.th, "new_bookings") == "🟢"

    def test_new_bookings_yellow(self) -> None:
        assert traffic_light(2, self.th, "new_bookings") == "🟡"

    def test_new_bookings_red(self) -> None:
        assert traffic_light(0, self.th, "new_bookings") == "🔴"


class TestRevenue:
    def test_adr(self) -> None:
        assert calc_adr(100000, 20) == 5000.0

    def test_adr_zero(self) -> None:
        assert calc_adr(100000, 0) is None

    def test_revpar(self) -> None:
        assert calc_revpar(88000, 44) == 2000.0

    def test_revpar_zero(self) -> None:
        assert calc_revpar(88000, 0) is None

    def test_revpar_from_adr(self) -> None:
        assert calc_revpar_from_adr_occupancy(5000, 68.18) == 3409.0

    def test_als(self) -> None:
        assert calc_als(60, 20) == 3.0

    def test_als_zero(self) -> None:
        assert calc_als(60, 0) is None


class TestResolveRevenue:
    def test_actual_priority(self) -> None:
        result = resolve_revenue(
            actual_revenue=50000.0,
            snapshot_price=3000.0,
            occupied_unit_nights=10,
        )
        assert result == RevenueResult(revenue=50000.0, is_estimated=False)

    def test_snapshot_fallback(self) -> None:
        result = resolve_revenue(actual_revenue=None, snapshot_price=4500.0, occupied_unit_nights=8)
        assert result == RevenueResult(revenue=36000.0, is_estimated=True)

    def test_zero_occupied(self) -> None:
        result = resolve_revenue(actual_revenue=None, snapshot_price=4500.0, occupied_unit_nights=0)
        assert result == RevenueResult(revenue=0.0, is_estimated=True)

    def test_no_data(self) -> None:
        result = resolve_revenue(actual_revenue=None, snapshot_price=None, occupied_unit_nights=5)
        assert result == RevenueResult(revenue=0.0, is_estimated=True)

    def test_zero_actual_uses_fallback(self) -> None:
        result = resolve_revenue(actual_revenue=0.0, snapshot_price=1000.0, occupied_unit_nights=3)
        assert result == RevenueResult(revenue=0.0, is_estimated=False)


class TestComputeDailyMetrics:
    def test_with_actual_revenue(self) -> None:
        m = compute_daily_metrics(
            sold_unit_nights=20,
            available_unit_nights=44,
            total_stay_days=45,
            bookings_count=15,
            actual_revenue=100000.0,
        )
        assert m == DailyMetrics(
            occupancy_pct=45.45,
            adr=5000.0,
            revpar=2272.73,
            als=3.0,
            revenue=100000.0,
            is_estimated=False,
        )

    def test_with_estimated_revenue(self) -> None:
        m = compute_daily_metrics(
            sold_unit_nights=10,
            available_unit_nights=44,
            total_stay_days=0,
            bookings_count=0,
            snapshot_price=5000.0,
        )
        assert m.revenue == 50000.0
        assert m.is_estimated is True
        assert m.adr == 5000.0
        assert m.als is None

    def test_empty_day(self) -> None:
        m = compute_daily_metrics(
            sold_unit_nights=0,
            available_unit_nights=44,
            total_stay_days=0,
            bookings_count=0,
        )
        assert m.occupancy_pct == 0.0
        assert m.adr is None
        assert m.revpar == 0.0
        assert m.revenue == 0.0
        assert m.is_estimated is True
