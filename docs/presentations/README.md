# Презентации 1apart

Материалы для заказчика (Екатерина Лопакова).

Исходная папка: `Documents/Люди/Лопакова Екатерина/презентации`

## Структура

```text
docs/presentations/
├── Презентация_1apart_с_заметками_12слайдов.pptx   # для заказчика (1apart)
├── travelline/
│   ├── TravelLine_партнёрское_предложение.pptx      # B2B-питч для TravelLine
│   └── assets/                                      # схемы для TL-презентации
├── speaker_notes.md
├── assets/                                          # PNG для клиентской презентации
├── build/
├── archive/
└── video/
```

## Сборка клиентской презентации (1apart)

```bash
# данные прогноза с VPS (опционально)
python scripts/export_presentation_data.py > docs/presentations/build/presentation_data.json

# PNG для слайдов 6–8
python scripts/build_presentation_assets.py

# обновление pptx
python scripts/update_presentation_1apart.py
```

## Актуальный файл для показа

`Презентация_1apart_с_заметками_12слайдов.pptx`

## Сборка презентации TravelLine (B2B)

```bash
python scripts/build_travelline_assets.py
python scripts/build_travelline_presentation.py
```

Файл: `docs/presentations/travelline/TravelLine_партнёрское_предложение.pptx` (10 слайдов, 7–10 мин)
