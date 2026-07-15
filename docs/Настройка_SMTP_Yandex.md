# Пошаговый план настройки SMTP через Яндекс Почту

Инструкция для Сергея. Для еженедельного email-отчёта hotel-report-bot.

Код (`email_sender.py`) использует **STARTTLS на порту 587** — не SSL/465.

---

## 0. Главное заранее

⚠️ Нужен **пароль приложения**, не обычный пароль от Яндекса.

Правила Яндекса:
- `SMTP_PASSWORD` = пароль приложения;
- `email.from_address` **обязан совпадать** с `SMTP_USER` (нельзя слать «от чужого» адреса).

Официальные настройки Яндекс SMTP:
| Параметр | Вариант A (STARTTLS) | Вариант B (SSL) |
|---|---|---|
| SMTP-сервер | `smtp.yandex.ru` | `smtp.yandex.ru` |
| Порт | `587` | `465` |
| Флаги | `SMTP_USE_TLS=true`, `SMTP_USE_SSL=false` | `SMTP_USE_TLS=false`, `SMTP_USE_SSL=true` |
| Логин | полный адрес (`bogdanchik2@yandex.ru`) | то же |
| Пароль | пароль приложения | то же |

Код поддерживает оба варианта. В dry_run письмо уходит на `email.test_addresses` (не на `to_addresses`).

---

## Шаг 1. Включить доступ по клиентам

1. Откройте [id.yandex.ru](https://id.yandex.ru/) → войдите в нужный ящик.
2. **Безопасность** → найдите блок про **пароли приложений** / доступ почтовых программ.
3. Включите возможность создавать пароли приложений (если просят — подтвердите телефон).

Альтернативный путь в веб-почте: [mail.yandex.ru](https://mail.yandex.ru/) → шестерёнка → **Все настройки** → **Почтовые программы** → разрешить доступ по протоколу.

---

## Шаг 2. Создать пароль приложения

1. В настройках безопасности Яндекса: **Пароли приложений** → **Создать новый пароль**.
2. Название, например: `hotel-report-bot`.
3. Скопируйте выданный пароль **сразу** (показывается один раз).

Этот пароль идёт в `SMTP_PASSWORD` на сервере. В Git **не коммитить**.

---

## Шаг 3. Прописать в проект

### `config/.env` (на VPS и локально, не в Git)

Вариант A — 587 + STARTTLS:

```
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=587
SMTP_USER=bogdanchik2@yandex.ru
SMTP_PASSWORD=ваш_пароль_приложения
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

Вариант B — 465 + SSL:

```
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=bogdanchik2@yandex.ru
SMTP_PASSWORD=ваш_пароль_приложения
SMTP_USE_TLS=false
SMTP_USE_SSL=true
```

### Важно для VPS

Многие хостинги **блокируют исходящие порты 25/465/587**.  
Если с сервера письмо не уходит, а локально уходит — попросите провайдера открыть исходящий SMTP или используйте транзакционный API по HTTPS.

В dry_run получатели берутся из `email.test_addresses` (обязательно задайте список).

### `config/settings.yaml`

В коде поле называется **`to_addresses`** (не `recipients`):

```yaml
email:
  from_address: bogdanchik2@yandex.ru   # = SMTP_USER
  to_addresses:
    - ваш_email@example.com
  subject_prefix: "[1apart] Еженедельный отчёт"
```

После правок — перезапуск сервиса (Docker: `docker compose ... up -d`).

---

## Шаг 4. Проверка в dry_run

1. В `settings.yaml`: `dry_run: true`.
2. Запустить отправку недельного отчёта (из админки или скриптом/задачей планировщика).
3. Письмо должно прийти на адрес из `to_addresses`.

Если ошибка аутентификации:
- пересоздайте пароль приложения;
- проверьте порт **587** и `SMTP_USE_TLS=true`;
- убедитесь, что `from_address == SMTP_USER`.

---

## Связь с боевым запуском (Issue #8)

- ✅ Google Sheets
- ✅ SMTP Yandex (этот документ)
- ✅ Max chat_id
- ⏳ TravelLine API — `docs/Настройка_TravelLine_API.md`
