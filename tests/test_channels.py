"""Тесты классификации каналов."""

from src.config import ChannelsMap
from src.metrics.guests import classify_channel, classify_channels


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


def test_empty_channel() -> None:
    cm = ChannelsMap(direct=["1apart.ru"], aggregator=["Островок"])
    assert classify_channel("", cm) == "unknown"
    assert classify_channel("   ", cm) == "unknown"


def test_classify_channels_batch() -> None:
    cm = ChannelsMap(
        direct=["1apart.ru"],
        aggregator=["Островок"],
    )
    result = classify_channels(["1apart.ru", "Островок", "Другое"], cm)
    assert result == {
        "1apart.ru": "direct",
        "Островок": "aggregator",
        "Другое": "unknown",
    }


def test_direct_priority_over_aggregator() -> None:
    """Прямой канал проверяется первым."""
    cm = ChannelsMap(
        direct=["Сайт"],
        aggregator=["Сайт партнёра"],
    )
    assert classify_channel("Сайт 1apart.ru", cm) == "direct"
