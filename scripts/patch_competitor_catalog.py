"""Дописать catalog_url для Центрального и Xander в рабочий settings.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

SETTINGS = Path("config/settings.yaml")


def main() -> None:
    data = yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))
    for item in data.get("competitors", []):
        name = item.get("name", "")
        if name == "Центральный":
            item["catalog_url"] = "http://centraltomsk.ru/rooms/"
            item["booking_url"] = "http://centraltomsk.ru/booking/"
            print("→ Центральный: catalog_url + booking_url")
        if name == "Xander Hotel":
            item["catalog_url"] = "https://xanderhotel.ru/ru/nomera-i-tseny.html"
            print("→ Xander Hotel: catalog_url")
    SETTINGS.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Сохранено: {SETTINGS}")


if __name__ == "__main__":
    main()
