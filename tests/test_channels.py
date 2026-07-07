"""Тесты классификации каналов."""

from src.config import ChannelsMap
from src.metrics.guests import classify_channel


def test_direct_site() -> None:
    cm = ChannelsMap(
        direct=["1apart.ru", "Звонок"],
        aggregator=["Островок", "Авито"],
    )
    assert classify_channel("1apart.ru", cm) == "direct"


def test_direct_phone() -> None:
    cm = ChannelsMap(direct=["Звонок"], aggregator=["Островок"])
    assert classify_channel("Входящий звонок", cm) == "direct"


def test_aggregator() -> None:
    cm = ChannelsMap(
        direct=["1apart.ru"],
        aggregator=["Островок", "Яндекс Путешествия"],
    )
    assert classify_channel("Островок", cm) == "aggregator"


def test_unknown() -> None:
    cm = ChannelsMap(direct=["1apart.ru"], aggregator=["Островок"])
    assert classify_channel("Неизвестный канал", cm) == "unknown"
