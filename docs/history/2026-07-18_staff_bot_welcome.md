# 2026-07-18 — Внутренний бот сотрудников Max (приветствие + ACL)

## Что сделано

- SCHEMA 17: таблицы `staff_users`, `staff_command_log`
- Пакет `src/staff_bot/`: ACL (owner/manager/viewer), шаблоны меню, handlers, dialog
- Webhook обрабатывает `bot_started`, `message_created`, `message_callback`
- Режим `staff_bot.dry_run=true`: отвечает только `test_user_ids`
- Неизвестным: «Доступ не предоставлен»
- Кнопка «Подробнее» → краткий план + ссылка в админку

## Конфиг

```yaml
staff_bot:
  enabled: true
  dry_run: true
  test_user_ids: [364502022]
  employees:
  - user_id: 364502022
    name: Сергей
    role: owner
```

## Дальше

1. Написать боту `/start` → в логах увидеть user_id Екатерины
2. Добавить её в `employees` + `test_user_ids`
3. После проверки выставить `staff_bot.dry_run: false`
