# 17.07.2026 — Max 2-КК, prompts/, Issue #13 почта

## Max
- Короткие подписи категорий в сводке Max: `category_short_label` (1-КК / 2-КК).

## Промпты
- `src/analytics/prompt_loader.py` — чтение `prompts/00` + задачный файл.
- `ai_insights._call_llm` использует файлы; fallback `_rule_based_cards` сохранён.
- Каркас `reviews_insights.py` (00+02) для Issue #16.

## Issue #13
- `mail_inbox` в settings; IMAP_* в `.env.example`.
- `mail_inbox.py` + `mail_report_parsers.py` (TravelLine).
- SQLite schema v7: `mail_messages`.
- Job `mail_inbox` (если enabled); `scripts/run_mail_inbox.py`.
