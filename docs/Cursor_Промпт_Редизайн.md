# Промпт для Cursor — редизайн админки в фирменном стиле 1apart.ru

> Скопируйте текст ниже (от строки `====` до конца) в чат Cursor (Agent / Composer, режим редактирования всего проекта) и запустите. Редизайн применяется одним заходом, функциональность не меняется.

====

Ты — фронтенд-разработчик с сильным вкусом к дизайну. В существующем проекте `hotel-report-bot` нужно сделать РЕДИЗАЙН веб-админки (FastAPI + Jinja2) в фирменном стиле сайта 1apart.ru — «навести красоту и блеск», НЕ трогая функциональность. Работай централизованно через CSS в `src/web/templates/base.html` (все шаблоны его наследуют). Комментарии — на русском.

## ЖЁСТКОЕ ПРАВИЛО
Ни одна кнопка, форма, ссылка, таблица, переключатель dry-run, авторизация, отдача скриншотов НЕ должны перестать работать. Не менять маршруты, Jinja-переменные, `{% block %}`, имена классов, используемых в шаблонах (`.card`, `.badge`, `.badge-green/-yellow`, `.grid-2`, `.big`, `.muted`, `.chart-bars`, `.bar`, `.sparkline`, `.trend-item`, `.idea-week`, `.takeaway`, `.competitor-card`, `.detail-grid`, `.screenshot-thumb` и др.) — их СТИЛИ переопределять, но не удалять. Сохранить адаптивность (`@media(max-width:768px)`).

## Фирменный стиль (взят с сайта 1apart.ru)
Премиальный «апарт-отельный»: золотисто-бежевый акцент, тёмная шапка, заголовки узким гротеском Oswald, текст Arial.

### 1. Подключить шрифты и задать CSS-переменные (в начало `<style>` в base.html)
```css
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&display=swap');
:root {
  --bg:        #FAF8F5;
  --surface:   #FFFFFF;
  --surface-2: #F6F1EA;
  --border:    #E6DDCF;
  --text:      #1B1B1B;
  --text-muted:#7A756C;
  --dark:      #121212;
  --dark-brown:#3B170B;
  --primary:   #C19B6A;   /* фирменное золото */
  --primary-h: #A9824F;
  --primary-2: #DCB179;
  --primary-soft:#F5EBDC;
  --ok:#2E7D32; --ok-bg:#E8F3E6;
  --warn:#B26A00; --warn-bg:#F7EAD2;
  --err:#B3261E; --err-bg:#F6E2DD;
  --radius:10px; --radius-sm:6px;
  --shadow:0 1px 2px rgba(59,23,11,.06),0 4px 14px rgba(59,23,11,.06);
  --shadow-hover:0 2px 6px rgba(59,23,11,.10),0 10px 28px rgba(59,23,11,.10);
}
body { font-family: Arial,'Helvetica Neue',Helvetica,sans-serif; background:var(--bg); color:var(--text); line-height:1.55; }
h1,h2,h3,.brand,.big { font-family:'Oswald',Arial,sans-serif; letter-spacing:.01em; }
```

### 2. Контраст (важно!)
Золото `#C19B6A` на белом — низкий контраст. Поэтому:
- золото — фон кнопок/плашек, границы, активное подчёркивание, акценты;
- текст-ссылки и важный текст на белом — `--dark-brown` (#3B170B) или `--primary-h`;
- на тёмной шапке золото — как акцент текста.
Соблюсти WCAG AA (текст ≥4.5:1). Не полагаться только на цвет для статусов — оставить значки 🟢🟡🔴/точки.

### 3. Навигация (`nav`)
- Тёмная шапка `background:var(--dark)`, `position:sticky; top:0; z-index:10`, тень.
- Бренд «🏨 Первый Апарт-отель» — Oswald, белый, uppercase, слева (`margin-right:auto`).
- Ссылки: `#DDD` по умолчанию; hover/active — `--primary` + `border-bottom:2px solid var(--primary)`.
- «Выход» — справа, приглушённый.
- Мобильно: горизонтальный скролл, не ломать.

### 4. Компоненты (переопределить стили существующих классов)
- **.card**: `background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:1.5rem`. Кликабельные — hover `--shadow-hover` + `translateY(-1px)` с `transition:.15s ease`.
- **Таблицы**: `th` — `background:var(--surface-2); color:var(--text-muted); text-transform:uppercase; font-size:12px; letter-spacing:.02em`. Зебра (чётные строки `--surface-2`), hover строки `--primary-soft`, только горизонтальные границы `--border`. Числа — правое выравнивание + `font-variant-numeric:tabular-nums`.
- **.badge**: pill-форма; `.badge-green`→`--ok/--ok-bg`, `.badge-yellow`→`--warn/--warn-bg`; добавить красный вариант `--err/--err-bg`. Со значком/точкой.
- **Кнопки** (`form button`, `.btn-small`): фон `--primary` (можно градиент `--primary`→`--primary-2`), текст `--dark` или белый по контрасту, `--radius-sm`, hover `--primary-h`, `transition`. Вторичная — контурная (`border:1px solid var(--border)`).
- **Поля/select**: `border:1px solid var(--border); border-radius:var(--radius-sm)`; focus — рамка `--primary` + `box-shadow:0 0 0 3px var(--primary-soft)`. Фокус-стиль видимый (accessibility).
- **.big / KPI**: 2–2.25rem Oswald; подпись `--text-muted`; при наличии дельты — ↑ зелёная / ↓ красная.
- **Графики** (`.chart-bars .bar`, `.sparkline .spark-bar`): столбцы `--primary` с лёгким градиентом, закруглить верх, `title`-тултип со значением. Без 3D/лишних сеток.

### 5. Разделы Конкуренты и Тренды
- **Конкуренты**: бейджи типа direct/indirect разного оттенка золота; `.screenshot-thumb` в рамке `--radius-sm`; блок «Мы vs рынок» (`.vs-block`) на `--surface-2`.
- **Тренды**: `.trend-item` — бейдж категории (золотой контур), флажок 🇷🇺/🌍, дата muted; `.takeaway` на `--primary-soft` с левой полосой `--primary`; `.idea-week` — выделенная карточка с золотой рамкой и подписью «Идея недели».

### 6. Экран входа (`login.html`)
Центрированная карточка на `--bg`, бренд Oswald, поля и золотая кнопка по системе, аккуратная ошибка `--err`.

### 7. Блеск (мелочи)
- `transition:.15s ease` на ховерах ссылок/кнопок/карточек.
- Система отступов 4/8/12/16/24px; `main{max-width:1180px}`.
- Пустые состояния (`.muted`) — приглушённо, с иконкой, не голый текст.
- Favicon: SVG 🏨 или простой data-URI.

## Приёмка (проверить перед PR)
- Все страницы (Дашборд, Цены, Метрики, Каналы, Конкуренты, Тренды, Отчёты, Логи, Настройки, Вход) открываются, вид единый и «фирменный».
- Все кнопки/формы/dry-run/повторная отправка отчёта работают как раньше.
- Sticky-шапка не перекрывает контент; активный пункт золотой.
- Таблицы читаемы, числа выровнены, статусы различимы без цвета.
- Контраст WCAG AA (DevTools); мобильный вид (375/768px) не ломается.
- `pytest` и рендеры страниц (200/редирект) по-прежнему зелёные.

## Действие
Примени редизайн: перепиши `<style>` в base.html по дизайн-системе выше, при необходимости добавь тонкие обёртки для KPI/статусов в шаблонах (без изменения данных), обнови login.html и favicon. Сделай скриншоты «до/после» если возможно. Один PR «Редизайн админки в стиле 1apart.ru».
