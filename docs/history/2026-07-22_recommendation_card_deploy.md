# Деплой карточки внедрения рекомендации

Дата: 2026-07-22

## Деплой

- VPS: `91.229.11.147`, контейнер `docker-app-1`
- Скрипт: `scripts/vps_deploy_recommendation_card.sh`
- Схема БД после `init_db`: **17**
- `python-docx`: установлен
- Модули карточки: `fetch_recommendation_card`, `STATUS_LABELS` — OK

## Залитые файлы

- `src/storage/models.py`, `db.py`
- `src/config.py`
- `src/forecast/recommendations.py`, `recommendation_instructions.py`, `service.py`
- `src/notifiers/docx_export.py`
- `src/web/app.py`, `queries.py`
- `src/web/templates/forecast.html`, `recommendation_detail.html`
- `requirements.txt`

## Проверка

- Админка: https://bot.masterklepa.online/forecast
- Карточка: `/forecast/recommendation/{id}` (или редирект в Центр рекомендаций)
