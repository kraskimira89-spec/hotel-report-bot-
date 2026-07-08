# Этап 3 — точные CSS-селекторы для парсинга цен с 1apart.ru

Документ для разработчика к ТЗ v2.2. Проверено на реальной верстке сайта (июль 2026). Цель — пройти этап 3 без проб и ошибок.

---

## 🔑 Главное: цены только на главной странице

Базовые цены по всем категориям («от N руб») есть **только на главной** `https://1apart.ru/` — внутри карточек-слайдера. На страницах отдельных категорий (`/1room23`, `/1room` и т.д.) цен в HTML **нет** (0 вхождений).

**Вывод:** собирать все 6 базовых цен нужно с **ОДНОЙ страницы — главной**. Это лучше, чем обходить 7 URL: один запрос, минимум нагрузки и риска блокировки.

- Способ сбора: **httpx + BeautifulSoup** (статический HTML). Playwright НЕ нужен.
- robots.txt разрешает сбор (закрыт только `/manager/`).
- Цены на конкретные даты (Price Optimizer) здесь НЕ берём — они внутри виджета TravelLine на `/booking`, их берём через TravelLine API (этап 7).

---

## Структура HTML карточки категории

```html
<h3 class="item-sliderblock__title"> однокомнатные <br>квартиры<br> </h3>
<a class="btn-brow-arrowed" href="1room23"><span>Подробнее</span></a>
...
<div class="item-sliderblock__footer footer-sliderblock">
  <div class="footer-sliderblock__main">
    <div class="footer-sliderblock__row">
      <span>23 м²</span>
      <span>от 4500 р</span>
    </div>
  </div>
</div>
```

---

## Селекторы (BeautifulSoup)

| Данные | Селектор | Примечание |
|---|---|---|
| Контейнер карточки | `.item-sliderblock` | родитель title и footer |
| Название категории | `.item-sliderblock__title` | убрать теги `<br>`, схлопнуть пробелы |
| Ключ категории (slug) | `a.btn-brow-arrowed` → атрибут `href` | напр. `1room23` — надёжный ключ |
| Строка «площадь + цена» | `.footer-sliderblock__row` | внутри два `<span>` |
| Площадь | первый `<span>` в строке | напр. «23 м²» |
| Цена | второй `<span>` в строке | напр. «от 4500 р» → взять только цифры → `int` |

---

## Эталонная привязка (7 карточек = 6 категорий + 1 дубль 60 м²)

| Название | Площадь | Цена | href (slug) |
|---|---|---|---|
| Однокомнатные квартиры с диванчиком | 30 м² | 5800 | `family-30` |
| Однокомнатные квартиры | 23 м² | 4500 | `1room23` |
| Однокомнатные квартиры | 27 м² | 5000 | `1room` |
| Улучшенные однокомнатные квартиры | 30 м² | 5500 | `uluchshennyie-odnokomnatnyie-kvartiryi` |
| Двухкомнатная квартира (2 кровати) | 60 м² | 6800 | `dvuxkomnatnyie-kvartiryi-(2-krovati)` |
| Двухкомнатная квартира (3 кровати) | 60 м² | 6800 | `dvuxkomnatnyie-kvartiryi-3` |
| Двухкомнатные квартиры люкс | 80 м² | 9900 | `80m2-apartamentyi` |

⚠️ Две категории по 60 м² имеют одинаковую цену (6800). **Различать по `href`/названию, а не по паре площадь+цена.**

---

## Что изменить в текущем `src/data_sources/site_prices.py`

1. **Источник:** не обходить `category_urls` по очереди, а сделать **один запрос на `base_url` (главная)** и распарсить все карточки. `category_urls` оставить как fallback/резерв.
2. **Селекторы:** заменить текущие `[data-price]` и `.price-value` — на реальном сайте их НЕТ. Использовать `.item-sliderblock` / `.footer-sliderblock__row` / два `<span>`.
3. **Ключ категории:** брать из `href` (slug) карточки.
4. **Анти-блок, backoff, User-Agent, паузы** — оставить как есть, реализовано корректно.

---

## Пример логики парсинга (одна главная страница)

```python
from bs4 import BeautifulSoup

def parse_home_prices(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select(".item-sliderblock"):
        title_el = card.select_one(".item-sliderblock__title")
        link_el = card.select_one("a.btn-brow-arrowed")
        row = card.select_one(".footer-sliderblock__row")
        if not (title_el and row):
            continue
        spans = row.find_all("span")
        if len(spans) < 2:
            continue
        title = " ".join(title_el.get_text(" ", strip=True).split())
        slug = link_el["href"].strip("/") if link_el else None
        area = spans[0].get_text(strip=True)        # "23 м²"
        price_raw = spans[1].get_text(strip=True)    # "от 4500 р"
        price = int("".join(c for c in price_raw if c.isdigit()))
        results.append({
            "slug": slug,
            "title": title,
            "area": area,
            "price": price,
        })
    return results
```

---

## Обновить тест `tests/test_site_prices.py`

- Фикстуру в `tests/fixtures/` заменить на сохранённый HTML **главной страницы** (не категории).
- Проверять, что парсер возвращает **7 карточек**.
- Проверять, что для `href="1room23"` цена = **4500**.
- Проверять, что обе карточки 60 м² (`dvuxkomnatnyie-kvartiryi-(2-krovati)` и `dvuxkomnatnyie-kvartiryi-3`) распознаются отдельно.

---

## Примечание по маппингу на 6 бизнес-категорий

Сайт показывает 7 карточек. Сопоставление со списком категорий заказчика (для отчётов) вести через `href` (slug) в конфиге — например, добавить в `config/settings.yaml` словарь `category_slug_map`, где каждому slug соответствует бизнес-название категории и код для метрик. Это отвяжет отчёты от возможных изменений названий на сайте.
