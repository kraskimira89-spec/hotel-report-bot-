# Карточка внедрения рекомендации

Дата: 2026-07-18

## Что сделано

- SCHEMA 14: снимок, selected_price, audit-поля applied/verified/rollback, комментарий менеджера
- Снимок JSON при создании рекомендации (не меняется после refresh для той же записи)
- Статусы: new → reviewed → accepted → applied → verified (+ rejected/deferred/expired/rolled_back)
- Страница `/forecast/recommendation/{id}` + экспорт Word (.docx)
- Инструкции TL по типам действия и конфигурируемые пороги отката
- Кнопки «Подробнее» / «Word» в таблице `/forecast`

## Файлы

- `src/storage/models.py`, `db.py`
- `src/forecast/recommendations.py`, `recommendation_instructions.py`, `service.py`
- `src/notifiers/docx_export.py`
- `src/web/app.py`, `queries.py`, `templates/forecast.html`, `recommendation_detail.html`
- `tests/test_recommendation_card.py`
- `requirements.txt` (+ python-docx)
