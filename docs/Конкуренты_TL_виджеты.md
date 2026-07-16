# Конкуренты с TravelLine / WuBook виджетами

## Почему не прямой IBE URL

`https://ru-ibe.tlintegration.ru/booking?context=TL-INT-…` часто отвечает **403 nginx**,
если открыть без origin сайта отеля. Рабочий путь:

1. Открыть сайт конкурента или `booking_url` (страница с iframe).
2. Дождаться iframe `booking2/hotel/index.gc.html` (TravelLine).
3. Нажать **НАЙТИ** в фильтре дат.
4. Считать min цену и категории из текста результатов.

## Даты

По умолчанию целевой горизонт: **завтра + 1 ночь** (`snapshot_date + 1 day`).
Виджет сам подставляет ближайшие доступные даты в форме.

## Конфиг

```yaml
- name: "Bon Apart (Банапарт)"
  url: "https://www.bon-apart.ru/"
  booking_url: "https://www.bon-apart.ru/booking/"  # опционально
  parser: tl_widget
```

## Ограничения

- Антибот / медленный сайт → graceful: цена `null`, остаётся последний снимок.
- WuBook и сайты без стабильного iframe могут остаться без цены.
- Vision-fallback (OpenAI) — только если DOM пуст и задан `OPENAI_API_KEY`.

## Issue

https://github.com/kraskimira89-spec/hotel-report-bot-/issues/19
