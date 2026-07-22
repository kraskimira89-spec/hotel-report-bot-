# TravelLine — партнёрское предложение

## Файлы

| Версия | Файл | Слайдов |
|--------|------|---------|
| v1 (исходник) | `TravelLine_партнёрское_предложение.pptx` | 10 |
| **v2 (актуальная)** | `TravelLine_партнёрское_предложение_v2.pptx` | 12 |
| PDF v2 | `TravelLine_партнёрское_предложение_v2.pdf` | — |

## Сборка v2

```bash
python scripts/build_travelline_presentation_v2.py
```

- Светлый B2B-стиль (#F6F8FB), тёмный титул и финал (#10243D)
- Сетка 16:9, контент с Y ≥ 1.45″ — без пересечений заголовков и карточек
- Заметки докладчика — в каждом слайде (Notes)
- Исходный v1 **не изменяется**

## Figma (дизайн-мастер)

Спецификация: [`figma-design-spec.md`](figma-design-spec.md)

```bash
# После подключения Figma MCP в Cursor:
python scripts/run_figma_travelline_v2.py
```

Скрипт deck: `scripts/figma/travelline_v2_deck.js` — 12 слайдов в Figma Slides с той же палитрой и сеткой, что pptx v2.


```bash
python scripts/build_travelline_presentation.py
```
