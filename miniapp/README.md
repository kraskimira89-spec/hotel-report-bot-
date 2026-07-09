# Мини-приложение MAX (Bridge + MAX UI)

Каркас для мини-приложения в мессенджере MAX.

- [MAX Bridge](https://dev.max.ru/docs/webapps/bridge) — CDN `max-web-app.js`, объект `window.WebApp`
- [MAX UI](https://dev.max.ru/ui) — `@maxhub/max-ui` (React 18+)

## Запуск

```bash
cd miniapp
npm install
npm run dev
```

Сборка: `npm run build` → `miniapp/dist/`

## Подключение к боту

В кабинете MAX: **Чат-боты → Расширенные настройки → URL мини-приложения** — HTTPS-адрес собранного `dist/`.

## Структура

- `index.html` — скрипт MAX Bridge
- `src/bridge.ts` — обёртка над `window.WebApp`
- `src/App.tsx` — экран на компонентах MAX UI
