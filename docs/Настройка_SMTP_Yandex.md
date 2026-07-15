# Настройка SMTP через Яндекс.Почту (bogdanchik2@yandex.ru)

Готовая памятка. Ящик `bogdanchik2@yandex.ru`, доступ по клиентам включён, пароль приложения создан.

## Значения для `.env` (под текущий код проекта — STARTTLS/587)

```
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=587
SMTP_USER=bogdanchik2@yandex.ru
SMTP_PASSWORD=<пароль_приложения_Яндекса>
SMTP_USE_TLS=true
```

## В `settings.yaml` (секция email)

```
email:
  from_address: bogdanchik2@yandex.ru   # ДОЛЖЕН совпадать с SMTP_USER
  recipients:
    - <email_получателя_отчёта>
```

## Почему порт 587, а не 465
Код `email_sender.py` использует `smtplib.SMTP(...)` + `server.starttls()` — это STARTTLS на порту **587**. Вариант SSL/465 (`SMTP_SSL`) в проекте не реализован. Яндекс поддерживает 587 со STARTTLS — рабочий штатный путь.

## Важно
- `SMTP_PASSWORD` — это **пароль приложения** Яндекса (id.yandex.ru → Безопасность → Пароли приложений), НЕ обычный пароль от почты.
- `from_address` обязан совпадать с `SMTP_USER` (`bogdanchik2@yandex.ru`) — Яндекс не даёт слать от чужого адреса.
- Предварительно в почте включено: «Пароли приложений и OAuth-токены» + доступ по IMAP (уже сделано).

## Проверка
1. Прописать значения в рабочий `.env` на сервере, получателей — в `settings.yaml`.
2. Перезапустить сервис/контейнер.
3. Запустить недельный отчёт в `dry_run` → письмо приходит на получателя.
4. Признак успеха: в логах нет `SMTP authentication failed`.

## На будущее (домен 1apart.ru)
Когда заведёте `report@1apart.ru` в Яндекс 360 — поменять только `SMTP_USER` и `from_address` на `report@1apart.ru` и создать для него новый пароль приложения. Остальное без изменений.
