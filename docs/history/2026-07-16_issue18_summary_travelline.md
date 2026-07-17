# 16.07.2026 — Issue #18: сводка из TravelLine

## Симптом
dry-run пайплайна: TL=13 броней, сводка `occupancy: 0`, `bookings: 0` (Sheets пуст).

## Причины
1. `get_stay_occupancy` ждал `bookingNumber`, а WebPMS отдаёт только `reservationId`.
2. `new_bookings_total` брался только из Sheets.

## Исправление
- Occupancy: фолбэк по строкам «Проживание» / `reservationId`.
- Bookings: TL (`get_channels`) основной, Sheets — фолбэк.
- Сверка: при Sheets=0 не поднимать расхождение.
- Логи `occupancy_source` / `bookings_source` в выводе пайплайна.

## Закрытие (17.07.2026)

Issue **#18 CLOSED**. Прогон VPS 17.07.2026: `occupancy=34.09`, `bookings=8`, `occ_src=travelline`, `book_src=travelline`, сверка OK.
Комментарий: https://github.com/kraskimira89-spec/hotel-report-bot-/issues/18#issuecomment-5000448989
