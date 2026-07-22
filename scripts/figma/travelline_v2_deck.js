// TravelLine v2 — Figma Slides deck (12 slides)
// Запуск: scripts/run_figma_travelline_v2.py (требует Figma MCP)

const C = {
  bgLight: { r: 246 / 255, g: 248 / 255, b: 251 / 255 },
  bgDark: { r: 16 / 255, g: 36 / 255, b: 61 / 255 },
  text: { r: 20 / 255, g: 32 / 255, b: 51 / 255 },
  muted: { r: 90 / 255, g: 107 / 255, b: 125 / 255 },
  white: { r: 1, g: 1, b: 1 },
  accent: { r: 36 / 255, g: 107 / 255, b: 206 / 255 },
  accent2: { r: 19 / 255, g: 168 / 255, b: 146 / 255 },
  card: { r: 1, g: 1, b: 1 },
  border: { r: 216 / 255, g: 224 / 255, b: 234 / 255 },
  highlight: { r: 232 / 255, g: 240 / 255, b: 250 / 255 },
  highlightGreen: { r: 232 / 255, g: 248 / 255, b: 244 / 255 },
};

const M = 79;
const Y_CONTENT = 208;
const W = 1920;
const H = 1080;
const CW = W - M * 2;
const ORG = "1apart · аналитика для объектов размещения";

await Promise.all([
  figma.loadFontAsync({ family: "Arial", style: "Regular" }),
  figma.loadFontAsync({ family: "Arial", style: "Bold" }),
]);

function addFrame(parent, x, y, w, h, fill, radius) {
  const f = figma.createFrame();
  parent.appendChild(f);
  f.resize(w, h);
  f.fills = [{ type: "SOLID", color: fill }];
  if (radius) f.cornerRadius = radius;
  f.x = x;
  f.y = y;
  return f;
}

function addText(parent, style, size, color, chars, x, y, w, h) {
  const t = figma.createText();
  parent.appendChild(t);
  t.fontName = { family: "Arial", style };
  t.fontSize = size;
  t.characters = chars;
  t.fills = [{ type: "SOLID", color }];
  if (w) {
    t.textAutoResize = "HEIGHT";
    t.resize(w, h || 200);
  }
  t.x = x;
  t.y = y;
  return t;
}

function addBar(parent, x, y, h, color) {
  const r = figma.createRectangle();
  parent.appendChild(r);
  r.resize(6, h);
  r.fills = [{ type: "SOLID", color }];
  r.cornerRadius = 3;
  r.x = x;
  r.y = y;
  return r;
}

function slideBg(slide, color) {
  slide.fills = [{ type: "SOLID", color }];
}

function footer(slide, n, dark) {
  addText(slide, "Regular", 11, dark ? C.muted : C.muted, ORG, M, 1018, 800, 24);
  addText(slide, "Regular", 11, dark ? C.muted : C.muted, String(n), W - M - 40, 1018, 40, 24);
}

function titleBar(slide, text, dark) {
  addText(slide, "Bold", 32, dark ? C.white : C.text, text, M, M, CW, 120);
}

function card(slide, x, y, w, h, title, body, accent) {
  const f = addFrame(slide, x, y, w, h, C.card, 12);
  f.strokes = [{ type: "SOLID", color: C.border }];
  f.strokeWeight = 1;
  addBar(f, 0, 0, h, accent || C.accent);
  addText(f, "Bold", 19, C.accent, title, 18, 14, w - 24, 40);
  addText(f, "Regular", 16, C.text, body, 18, 48, w - 24, h - 60);
  return f;
}

const slideIds = [];

// 1 Title
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgDark);
  addText(s, "Bold", 34, C.white, "От данных TravelLine —\nк ежедневным решениям владельца", M, 120, CW, 140);
  addText(
    s,
    "Regular",
    19,
    { r: 142 / 255, g: 197 / 255, b: 1 },
    "Партнёрское предложение:\nаналитика, прогноз и рекомендации для объектов размещения",
    M,
    300,
    CW,
    80
  );
  addText(s, "Regular", 16, C.muted, `${ORG} · 2026`, M, 560, CW, 30);
  footer(s, 1, true);
}

// 2 Problem
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Данные есть. Времени на своевременные решения — мало.");
  const cw = (CW - 26 * 2) / 3;
  const items = [
    ["Ручной контроль", "Таблицы, бронирования, цены и отчёты в разных местах.", C.accent],
    ["Решения с опозданием", "Цена и спрос меняются каждый день.", C.accent2],
    ["Нет следующего действия", "Владелец видит цифры, но не получает понятный план.", C.accent],
  ];
  items.forEach(([t, b, a], i) => card(s, M + i * (cw + 26), Y_CONTENT + 40, cw, 200, t, b, a));
  footer(s, 2, false);
}

// 3 Solution
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Аналитический слой, который усиливает данные TravelLine");
  const steps = [
    "TravelLine + PMS + сигналы рынка",
    "Прогноз и контроль",
    "Рекомендации и действия менеджера",
  ];
  let sy = Y_CONTENT + 40;
  steps.forEach((txt) => {
    const bx = M + CW / 2 - 260;
    const f = addFrame(s, bx, sy, 520, 52, C.highlight, 8);
    f.strokes = [{ type: "SOLID", color: C.accent }];
    f.strokeWeight = 1;
    addText(f, "Bold", 16, C.accent, txt, 16, 14, 488, 40);
    sy += 66;
  });
  const feats = ["Ежедневные показатели", "Прогноз загрузки", "Рыночные сигналы", "Контроль действий"];
  const fw = (CW - 26 * 3) / 4;
  feats.forEach((f, i) => card(s, M + i * (fw + 26), sy + 20, fw, 130, f, "Проверяется в пилоте", C.accent2));
  footer(s, 3, false);
}

// 4 Owner plan
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Не ещё один отчёт. А понятный план действий.");
  const steps = [
    ["1. Сигнал", "Растёт pickup, есть событие, цена ниже рынка."],
    ["2. Рекомендация", "Проверить цену конкретной категории."],
    ["3. Инструкция", "Пошаговые действия для менеджера."],
    ["4. Контроль", "Проверить результат через 24 часа."],
  ];
  const cw = 280;
  const gap = 36;
  const total = 4 * cw + 3 * gap;
  let x = M + (CW - total) / 2;
  steps.forEach(([t, b], i) => {
    card(s, x, Y_CONTENT + 40, cw, 220, t, b);
    x += cw;
    if (i < 3) {
      const arr = figma.createPolygon();
      s.appendChild(arr);
      arr.pointCount = 3;
      arr.resize(24, 18);
      arr.rotation = 90;
      arr.fills = [{ type: "SOLID", color: C.accent2 }];
      arr.x = x + 6;
      arr.y = Y_CONTENT + 140;
      x += gap;
    }
  });
  footer(s, 4, false);
}

// 5 Forecast + events
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Спрос можно увидеть раньше, чем он попадёт в отчёт");
  const half = (CW - 22) / 2;
  const y = Y_CONTENT + 40;
  const lf = addFrame(s, M, y, half, 320, C.card, 12);
  lf.strokes = [{ type: "SOLID", color: C.border }];
  lf.strokeWeight = 1;
  addText(lf, "Bold", 19, C.accent, "Прогноз на 7 / 14 / 30 / 180 дней", 18, 16, half - 36, 40);
  addText(
    lf,
    "Regular",
    16,
    C.text,
    "• загрузка;\n• ADR и RevPAR;\n• выручка;\n• сценарии и уровень уверенности.",
    18,
    56,
    half - 36,
    240
  );
  const div = figma.createRectangle();
  s.appendChild(div);
  div.resize(2, 280);
  div.fills = [{ type: "SOLID", color: C.border }];
  div.x = M + half + 10;
  div.y = y + 20;
  const rf = addFrame(s, M + half + 22, y, half, 320, C.card, 12);
  rf.strokes = [{ type: "SOLID", color: C.border }];
  rf.strokeWeight = 1;
  addText(rf, "Bold", 19, C.accent2, "События и рынок", 18, 16, half - 36, 40);
  addText(rf, "Regular", 16, C.text, "Конференции · концерты · спорт · фестивали", 18, 56, half - 36, 50);
  addText(
    rf,
    "Regular",
    16,
    C.muted,
    "Подтверждённые события помогают\nзаранее проверить цены и доступность.",
    18,
    110,
    half - 36,
    120
  );
  footer(s, 5, false);
}

// 6 Economics
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Ценность измеряется в сохранённом времени и качестве решений");
  const y = Y_CONTENT + 40;
  const f = addFrame(s, M, y, CW, 90, C.highlight, 10);
  f.strokes = [{ type: "SOLID", color: C.accent }];
  f.strokeWeight = 1;
  addText(
    f,
    "Bold",
    19,
    C.accent,
    "Экономия часов в месяц =\nежедневный ручной контроль + еженедельные отчёты + поиск и сверка данных",
    20,
    14,
    CW - 40,
    70
  );
  const kpis = ["До пилота:\n___ ч/мес.", "После пилота:\n___ ч/мес.", "Экономия:\n___ ч/мес.", "Эквивалент:\n___ ₽/мес."];
  const kw = (CW - 26 * 3) / 4;
  kpis.forEach((k, i) => {
    const cf = addFrame(s, M + i * (kw + 26), y + 110, kw, 120, C.card, 10);
    cf.strokes = [{ type: "SOLID", color: C.border }];
    cf.strokeWeight = 1;
    addText(cf, "Bold", 26, C.text, k, 12, 24, kw - 24, 90);
  });
  addText(
    s,
    "Regular",
    13,
    C.muted,
    "Финансовый эффект и рост выручки оцениваются отдельно по результатам пилота, без предварительных гарантий.",
    M,
    y + 250,
    CW,
    40
  );
  footer(s, 6, false);
}

// 7 TL value
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Дополнительная ценность для экосистемы TravelLine");
  const items = [
    ["Понятнее данные", "Владелец быстрее понимает ситуацию."],
    ["Больше регулярности", "Показатели превращаются в рабочие решения."],
    ["Новый продуктовый слой", "Возможный add-on или marketplace-интеграция."],
    ["Проверяемая гипотеза", "Ценность подтверждается пилотом, а не обещанием."],
  ];
  const cw = (CW - 26) / 2;
  const ch = 150;
  items.forEach(([t, b], i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    card(s, M + col * (cw + 26), Y_CONTENT + 40 + row * (ch + 26), cw, ch, t, b, col ? C.accent2 : C.accent);
  });
  footer(s, 7, false);
}

// 8 Webinar
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Начать можно с вебинара для клиентов TravelLine");
  const tl = [
    ["10 мин", "проблема владельца"],
    ["15 мин", "демонстрация сценариев"],
    ["10 мин", "прогноз и рекомендации"],
    ["10 мин", "вопросы и заявка в пилот"],
  ];
  const tw = (CW - 26 * 3) / 4;
  tl.forEach(([tm, lb], i) => {
    const x = M + i * (tw + 26);
    const f = addFrame(s, x, Y_CONTENT + 40, tw, 110, C.card, 10);
    f.strokes = [{ type: "SOLID", color: C.border }];
    f.strokeWeight = 1;
    addText(f, "Bold", 26, C.accent, tm, 8, 12, tw - 16, 40);
    addText(f, "Regular", 16, C.text, lb, 8, 52, tw - 16, 50);
  });
  const gf = addFrame(s, M, Y_CONTENT + 170, CW, 120, C.highlightGreen, 10);
  gf.strokes = [{ type: "SOLID", color: C.accent2 }];
  gf.strokeWeight = 1;
  addText(gf, "Bold", 19, C.accent2, "Цели:", 18, 14, 200, 30);
  addText(
    gf,
    "Regular",
    16,
    C.text,
    "• проверить интерес;  • собрать заявки в пилот;  • измерить текущие трудозатраты;\n• узнать готовность платить;  • определить востребованные функции.",
    18,
    44,
    CW - 36,
    70
  );
  footer(s, 8, false);
}

// 9 Pilot
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "Контролируемый пилот вместо большого риска");
  const rows = [
    ["TravelLine", "согласование API и подбор пилотных объектов"],
    ["Разработчик", "настройка, поддержка, аналитика результатов"],
    ["Объект", "доступ к данным и обратная связь менеджера"],
  ];
  rows.forEach(([role, resp], i) => {
    const y = Y_CONTENT + 40 + i * 86;
    const f = addFrame(s, M, y, CW, 72, C.card, 8);
    f.strokes = [{ type: "SOLID", color: C.border }];
    f.strokeWeight = 1;
    addText(f, "Bold", 19, C.accent, role, 18, 18, 220, 40);
    addText(f, "Regular", 16, C.text, resp, 250, 18, CW - 280, 40);
  });
  const rf = addFrame(s, M, Y_CONTENT + 310, CW, 80, C.highlight, 10);
  rf.strokes = [{ type: "SOLID", color: C.accent }];
  rf.strokeWeight = 1;
  addText(
    rf,
    "Bold",
    19,
    C.accent,
    "Результат пилота: подтверждённая ценность, спрос, экономика и модель масштабирования.",
    20,
    20,
    CW - 40,
    50
  );
  footer(s, 9, false);
}

// 10 Prospects
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "От пилота — к долгосрочному продукту");
  const st = [
    ["1. Пилот", "Проверка сценариев и спроса."],
    ["2. Продукт", "Дополнительный модуль или marketplace-интеграция."],
    ["3. Масштабирование", "Совместное предложение для сегментов клиентов TravelLine."],
  ];
  const sw = (CW - 26 * 2) / 3;
  st.forEach(([t, b], i) => card(s, M + i * (sw + 26), Y_CONTENT + 40, sw, 200, t, b, [C.accent, C.accent2, C.accent][i]));
  addText(
    s,
    "Regular",
    16,
    C.muted,
    "Возможные модели: лицензирование · add-on · revenue share · совместное внедрение.",
    M,
    Y_CONTENT + 260,
    CW,
    40
  );
  footer(s, 10, false);
}

// 11 Plan 90
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgLight);
  titleBar(s, "План на 90 дней");
  const blocks = [
    ["0–30 дней", "Согласование, вебинар, набор пилотных объектов."],
    ["31–60 дней", "Подключение, baseline показателей, обучение."],
    ["61–90 дней", "Измерение результата, анализ спроса и решение о масштабировании."],
  ];
  const bw = (CW - 26 * 2) / 3;
  blocks.forEach(([head, txt], i) => {
    const x = M + i * (bw + 26);
    const f = addFrame(s, x, Y_CONTENT + 40, bw, 280, C.card, 12);
    f.strokes = [{ type: "SOLID", color: C.border }];
    f.strokeWeight = 1;
    const circle = figma.createEllipse();
    f.appendChild(circle);
    circle.resize(40, 40);
    circle.fills = [{ type: "SOLID", color: C.accent }];
    circle.x = 16;
    circle.y = 16;
    addText(f, "Bold", 20, C.white, String(i + 1), 26, 22, 24, 24);
    addText(f, "Bold", 19, C.accent, head, 16, 68, bw - 32, 40);
    addText(f, "Regular", 16, C.text, txt, 16, 112, bw - 32, 150);
  });
  footer(s, 11, false);
}

// 12 Final
{
  const s = figma.createSlide();
  slideIds.push(s.id);
  slideBg(s, C.bgDark);
  addText(s, "Bold", 34, C.white, "Предлагаем проверить ценность вместе", M, 130, CW, 60);
  addText(
    s,
    "Regular",
    19,
    { r: 168 / 255, g: 184 / 255, b: 200 / 255 },
    "Не просто показать отчёт,\nа измерить, помогает ли решение\nвладельцу быстрее действовать по данным.",
    M,
    220,
    CW,
    100
  );
  addText(
    s,
    "Bold",
    19,
    C.accent2,
    "Следующий шаг:\nвстреча для согласования вебинара и пилота.",
    M,
    380,
    CW,
    60
  );
  addText(s, "Regular", 16, C.white, "Сергей Богдановский · bogdanchik2@yandex.ru · +7 909 195-04-08", M, 520, CW, 40);
  footer(s, 12, true);
}

return { slideIds, count: slideIds.length, file: "TravelLine v2" };
