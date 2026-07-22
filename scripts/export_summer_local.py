#!/usr/bin/env python3
"""Экспорт слайдов 08–12 из pptx v2 + копия pptx/pdf в summer/."""

from __future__ import annotations

import shutil
from pathlib import Path

import win32com.client

ROOT = Path(__file__).resolve().parents[1]
TRAVELLINE = ROOT / "docs" / "presentations" / "travelline"
OUT = TRAVELLINE / "summer"

NAMES = {
    8: "08_Webinar",
    9: "09_Pilot_Model",
    10: "10_Perspectives",
    11: "11_Roadmap",
    12: "12_Closing",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pptx_files = list(TRAVELLINE.glob("*_v2.pptx"))
    if not pptx_files:
        raise SystemExit("pptх v2 не найден")
    src = pptx_files[0]

    app = win32com.client.Dispatch("PowerPoint.Application")
    try:
        try:
            app.Visible = 1
        except Exception:
            pass
        pres = app.Presentations.Open(str(src.resolve()), WithWindow=False)
        try:
            tmp = OUT / "_pptx_export"
            tmp.mkdir(exist_ok=True)
            for i in range(1, pres.Slides.Count + 1):
                dest = tmp / f"slide_{i:02d}.png"
                pres.Slides(i).Export(str(dest), "PNG", 1920, 1080)
                print(f"exported {dest.name} ({dest.stat().st_size})")
            for idx, name in NAMES.items():
                src_png = tmp / f"slide_{idx:02d}.png"
                dst = OUT / f"{name}.png"
                dst.write_bytes(src_png.read_bytes())
                print(f"saved {dst.name}")
        finally:
            pres.Close()
    finally:
        app.Quit()

    shutil.copy2(src, OUT / "TravelLine_Summer_Data_Momentum.pptx")
    pdfs = list(TRAVELLINE.glob("*_v2.pdf"))
    if pdfs:
        shutil.copy2(pdfs[0], OUT / "TravelLine_Summer_Data_Momentum.pdf")

    print("files:", sorted(p.name for p in OUT.iterdir() if p.is_file()))


if __name__ == "__main__":
    main()
