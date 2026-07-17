# Промпт LLM для раздела «Прогноз»

**Дата:** 17.07.2026

## Сделано

- `prompts/04_forecast.md` — задачный промпт: горизонты 7/14/30/180, сценарии, границы, уверенность, цены
- `prompt_loader`: задача `forecast` = `00_system_base` + `04_forecast` + `03_recommendations`
- `src/analytics/forecast_insights.py` — сбор messages, LLM-вызов, rule-based fallback
- `/forecast` — блок «ИИ-комментарий к прогнозу»
- Тесты в `test_prompt_loader.py`
