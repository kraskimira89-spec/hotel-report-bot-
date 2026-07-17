# Дополнение ТЗ: «Мой бизнес» и массовые мероприятия

Дата: 2026-07-17

## Сделано

- SCHEMA **v12**: поля `is_online`, `registration_required`, `expected_attendance`,
  `attendance_source`, `tourism_relevance`, `overnight_likelihood`, `is_public_holiday`,
  `location_confirmed`
- Источники в `settings.example.yaml`:
  - `my_business_tomsk` (mb.tomsk.ru)
  - `tomsk_sport_calendar`
  - `tomsk_region_events` (gosuslugi, best-effort)
  - `tomsk_library_events`
  - `ria_tomsk_events` (`verification_only`)
- Парсеры + фикстуры; многодневный спорт → один период
- `overnight_likelihood`, `event_demand_score`; онлайн и вне Томска не в прогнозе
  (исключение: `location_confirmed`)
- Уведомление Max: approved + impact≥80 + overnight≥0.35 + ≤14 дней
- `scripts/patch_events_settings.py` мержит новые источники

## Приёмка

- [ ] Сборщики Мой бизнес / спорт / календарь на VPS
- [ ] Онлайн не влияет на прогноз
- [ ] Вне Томска — только после ручного подтверждения локации
- [ ] Источник и ссылка в карточке `/events`
