# Figma — TravelLine партнёрское предложение v2

Дизайн-система для Figma Slides, синхронизирована с `TravelLine_партнёрское_предложение_v2.pptx`.

## Подключение

1. Cursor → Settings → MCP → **Figma** → Connect (OAuth)
2. ```bash
   python scripts/run_figma_travelline_v2.py
   ```

Файл создаётся в Drafts: `TravelLine · партнёрское предложение v2`.

## Цвета (variables)

| Token | Hex | Использование |
|-------|-----|---------------|
| `bg/light` | `#F6F8FB` | Основной фон слайдов 2–11 |
| `bg/dark` | `#10243D` | Слайды 1, 12 |
| `text/primary` | `#142033` | Заголовки и body |
| `text/muted` | `#5A6B7D` | Подписи, footer |
| `text/onDark` | `#FFFFFF` | Текст на тёмном |
| `accent/primary` | `#246BCE` | Акцент, полоски карточек |
| `accent/secondary` | `#13A892` | Стрелки, второй акцент |
| `surface/card` | `#FFFFFF` | Карточки |
| `surface/highlight` | `#E8F0FA` | Формулы, блоки |
| `border/default` | `#D8E0EA` | Обводка карточек |

## Типографика

| Style | Font | Size | Weight |
|-------|------|------|--------|
| `Title/L` | Arial | 34 | Bold |
| `Title/M` | Arial | 32 | Bold |
| `Subtitle` | Arial | 19 | Regular |
| `Body` | Arial | 16 | Regular |
| `KPI` | Arial | 26 | Bold |
| `Footer` | Arial | 11 | Regular |

## Сетка 16:9

```text
Slide: 1920 × 1080 px (13.333 × 7.5 in)
Margin: 79 px (0.55 in)
Content Y min: 208 px (1.45 in)
Title zone max height: 151 px (1.05 in)
Gap title → content: 40 px (0.28 in)
Gap cards: 26 px (0.18 in)
Footer Y: 1018 px (7.05 in)
```

## Компоненты (создаются скриптом)

- **Slide/TitleBar** — заголовок + optional eyebrow
- **Slide/Card** — rounded rect + left accent bar + title + body
- **Slide/Arrow** — chevron между карточками
- **Slide/Footer** — org + номер слайда
- **Slide/TwoColumn** — прогноз | события
- **Slide/Timeline** — 4 блока вебинара

## 12 слайдов

См. ТЗ и `scripts/figma/travelline_v2_slides.js` — тексты 1:1 с pptx v2.

## Связь с кодом

| Артефакт | Путь |
|----------|------|
| PPTX v2 | `TravelLine_партнёрское_предложение_v2.pptx` |
| Сборка PPTX | `scripts/build_travelline_presentation_v2.py` |
| Figma Slides | `scripts/figma/travelline_v2_slides.js` |
| Runner | `scripts/run_figma_travelline_v2.py` |
