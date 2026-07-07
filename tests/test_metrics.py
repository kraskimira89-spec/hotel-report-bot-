"""Тесты формул метрик."""

from src.config import TrafficLightThresholds
from src.metrics.occupancy import calc_occupancy, traffic_light_status
from src.metrics.revenue import (
    calc_adr,
    calc_als,
    calc_revpar,
    calc_revpar_from_adr_occupancy,
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


class TestTrafficLight:
    def setup_method(self) -> None:
        self.th = TrafficLightThresholds()

    def test_occupancy_green(self) -> None:
        assert traffic_light_status(75, self.th, "occupancy") == "green"

    def test_occupancy_yellow(self) -> None:
        assert traffic_light_status(55, self.th, "occupancy") == "yellow"

    def test_occupancy_red(self) -> None:
        assert traffic_light_status(30, self.th, "occupancy") == "red"

    def test_price_change_green(self) -> None:
        assert traffic_light_status(2, self.th, "price_change") == "green"

    def test_price_change_red(self) -> None:
        assert traffic_light_status(15, self.th, "price_change") == "red"


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
