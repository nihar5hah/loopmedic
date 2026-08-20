/* LoopMedic — Minor Project Proposal deck (16:9) */
const pptxgen = require("pptxgenjs");

// ---------- palette ----------
const INK = "0A2E2A";      // deep teal ink (dark slides)
const INK2 = "0F3A35";     // dark card on ink
const TEAL = "028090";     // primary
const MINT = "02C39A";     // accent
const BG = "F5FAF8";       // light slide bg
const CARD = "FFFFFF";
const BORDER = "D8E8E4";
const BODY = "1F3A38";     // body text on light
const MUTED = "5B7370";
const DANGER = "C8443E";
const DANGER_BG = "FCEAE8";
const LIGHT_TEXT = "D7EDE8";
const MUTED_DARK = "8FB8B0";

const TITLE_FONT = "Trebuchet MS";
const BODY_FONT = "Calibri";
const MONO_FONT = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Nihar Shah";
pres.title = "LoopMedic — Minor Project Proposal";

const PW = 10, PH = 5.625, MX = 0.55; // page width/height, margin x

// ---------- helpers ----------
function logoMark(slide, x, y, s, boxColor, crossColor) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w: s, h: s, fill: { color: boxColor }, rectRadius: s * 0.18,
  });
  const bar = s * 0.62, thick = s * 0.2, off = (s - bar) / 2, toff = (s - thick) / 2;
  slide.addShape(pres.shapes.RECTANGLE, { x: x + off, y: y + toff, w: bar, h: thick, fill: { color: crossColor } });
  slide.addShape(pres.shapes.RECTANGLE, { x: x + toff, y: y + off, w: thick, h: bar, fill: { color: crossColor } });
}

function header(slide, eyebrow, title, dark = false) {
  slide.addText(eyebrow, {
    x: MX, y: 0.38, w: 7.5, h: 0.26, margin: 0,
    fontFace: MONO_FONT, fontSize: 10, charSpacing: 3,
    color: dark ? MINT : TEAL, bold: true,
  });
  slide.addText(title, {
    x: MX, y: 0.64, w: 8.4, h: 0.62, margin: 0,
    fontFace: TITLE_FONT, fontSize: 29, bold: true,
    color: dark ? "FFFFFF" : BODY,
  });
  logoMark(slide, PW - MX - 0.34, 0.42, 0.34, dark ? MINT : TEAL, dark ? INK : "FFFFFF");
}

function footer(slide, dark = false) {
  slide.addText("LoopMedic — minor project proposal", {
    x: MX, y: PH - 0.32, w: 4, h: 0.2, margin: 0,
    fontFace: MONO_FONT, fontSize: 7.5, color: dark ? MUTED_DARK : MUTED,
  });
}

function arrow(slide, x, y, w, h, color, dashed = false, bothEnds = false) {
  // negative w/h corrupt the file — normalize and flip direction instead
  slide.addShape(pres.shapes.LINE, {
    x: w < 0 ? x + w : x,
    y: h < 0 ? y + h : y,
    w: Math.abs(w),
    h: Math.abs(h),
    flipH: w < 0,
    flipV: h < 0,
    line: {
      color, width: 1.75,
      dashType: dashed ? "dash" : "solid",
      endArrowType: "triangle",
      beginArrowType: bothEnds ? "triangle" : "none",
    },
  });
}

function arrowLabel(slide, text, x, y, w, color) {
  slide.addText(text, {
    x, y, w, h: 0.18, margin: 0, align: "center",
    fontFace: MONO_FONT, fontSize: 8, color,
  });
}

// ============================================================
// S1 — TITLE (dark)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: INK };

  // decorative soft circles, right side
  for (const [cx, cy, d] of [[7.6, 1.3, 2.6], [8.35, 1.65, 1.5], [7.2, 2.6, 3.4]]) {
    s.addShape(pres.shapes.OVAL, {
      x: cx - d / 2, y: cy - d / 2, w: d, h: d,
      fill: { type: "none" }, line: { color: "1D4A44", width: 1 },
    });
  }

  logoMark(s, MX, 0.55, 0.52, MINT, INK);

  s.addText("MINOR PROJECT // PROJECT DEFINITION", {
    x: MX, y: 1.55, w: 7, h: 0.28, margin: 0,
    fontFace: MONO_FONT, fontSize: 11, charSpacing: 4, color: MINT, bold: true,
  });
  s.addText("LoopMedic", {
    x: MX, y: 1.85, w: 8.5, h: 1.0, margin: 0,
    fontFace: TITLE_FONT, fontSize: 54, bold: true, color: "FFFFFF",
  });
  s.addText("Grounded runtime supervision & recovery for tool-using LLM agents", {
    x: MX, y: 2.85, w: 8.2, h: 0.4, margin: 0,
    fontFace: BODY_FONT, fontSize: 17, color: LIGHT_TEXT,
  });
  s.addText(
    "A supervisor between an AI agent and its tools that watches what the agent actually does to a real database — and stops it from making things worse.",
    { x: MX, y: 3.32, w: 6.6, h: 0.75, margin: 0, fontFace: BODY_FONT, fontSize: 12.5, color: MUTED_DARK, italic: true }
  );

  // faux-trace teaser card
  s.addShape(pres.shapes.RECTANGLE, { x: 6.35, y: 4.05, w: 3.15, h: 1.05, fill: { color: INK2 }, line: { color: "1D4A44", width: 1 } });
  s.addText([
    { text: "attempt a31 · create_appointment", options: { breakLine: true } },
    { text: "ledger: SUCCEEDED · response: LOST", options: { breakLine: true } },
    { text: "verdict: verified result → no duplicate", options: { color: MINT } },
  ], {
    x: 6.5, y: 4.16, w: 2.9, h: 0.85, margin: 0,
    fontFace: MONO_FONT, fontSize: 8.5, color: LIGHT_TEXT, paraSpaceAfter: 4,
  });

  s.addText("Nihar Shah  ·  August 2026", {
    x: MX, y: PH - 0.5, w: 5, h: 0.25, margin: 0,
    fontFace: MONO_FONT, fontSize: 10, color: MUTED_DARK,
  });
}

// ============================================================
// S2 — PROBLEM STATEMENT
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "01 // PROBLEM STATEMENT", "Agents act. Nobody checks.");
  footer(s);

  s.addText([
    { text: "LLM agents now book, cancel, and reschedule in real systems through tool protocols like MCP.", options: { bullet: { code: "2022", indent: 14 }, breakLine: true } },
    { text: "Tool calls fail ambiguously: a write can commit while its response is lost — the agent sees only a timeout.", options: { bullet: { code: "2022", indent: 14 }, breakLine: true } },
    { text: "The natural fix — blind retry — silently creates duplicate bookings and corrupt state.", options: { bullet: { code: "2022", indent: 14 }, breakLine: true } },
    { text: "Agents also declare “done” when the task isn’t, and nothing verifies the claim against actual system state.", options: { bullet: { code: "2022", indent: 14 } } },
  ], {
    x: MX, y: 1.6, w: 4.55, h: 2.9, margin: 0,
    fontFace: BODY_FONT, fontSize: 12.5, color: BODY, paraSpaceAfter: 10,
  });

  s.addText("The agent did nothing stupid — the infrastructure lied to it.", {
    x: MX, y: 4.62, w: 4.55, h: 0.35, margin: 0,
    fontFace: BODY_FONT, fontSize: 12, italic: true, color: TEAL,
  });

  // failure vignette card
  const cx = 5.45, cy = 1.55, cw = 4.0, ch = 3.55;
  s.addShape(pres.shapes.RECTANGLE, {
    x: cx, y: cy, w: cw, h: ch, fill: { color: CARD }, line: { color: BORDER, width: 1 },
    shadow: { type: "outer", color: "0A2E2A", blur: 8, offset: 2, angle: 90, opacity: 0.10 },
  });
  s.addText("POST-COMMIT RESPONSE LOSS", {
    x: cx + 0.25, y: cy + 0.18, w: cw - 0.5, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9.5, charSpacing: 2, color: DANGER, bold: true,
  });

  const bx = cx + 0.55, bw = cw - 1.1;
  const boxes = [
    { t: "write commits in SQLite", y: cy + 0.55, danger: false },
    { t: "response never arrives — agent sees a timeout", y: cy + 1.35, danger: false },
    { t: "blind retry executes the same write again", y: cy + 2.15, danger: false },
  ];
  for (const b of boxes) {
    s.addText(b.t, {
      x: bx, y: b.y, w: bw, h: 0.5, margin: 0, align: "center", valign: "middle",
      fontFace: BODY_FONT, fontSize: 10.5, color: BODY,
      fill: { color: BG }, line: { color: BORDER, width: 1 },
    });
  }
  arrow(s, bx + bw / 2, cy + 1.06, 0, 0.27, MUTED);
  arrow(s, bx + bw / 2, cy + 1.86, 0, 0.27, MUTED);
  s.addText("2 × CONFIRMED appointments", {
    x: bx, y: cy + 2.78, w: bw, h: 0.5, margin: 0, align: "center", valign: "middle",
    fontFace: BODY_FONT, fontSize: 11.5, bold: true, color: DANGER,
    fill: { color: DANGER_BG }, line: { color: DANGER, width: 1 },
  });
}

// ============================================================
// S3 — TEAM
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "02 // TEAM", "Team");
  footer(s);

  // member card
  const cx = MX, cy = 1.7, cw = 4.3, ch = 2.7;
  s.addShape(pres.shapes.RECTANGLE, {
    x: cx, y: cy, w: cw, h: ch, fill: { color: CARD }, line: { color: BORDER, width: 1 },
    shadow: { type: "outer", color: "0A2E2A", blur: 8, offset: 2, angle: 90, opacity: 0.10 },
  });
  s.addShape(pres.shapes.OVAL, { x: cx + 0.3, y: cy + 0.3, w: 0.85, h: 0.85, fill: { color: MINT } });
  s.addText("NS", {
    x: cx + 0.3, y: cy + 0.3, w: 0.85, h: 0.85, margin: 0, align: "center", valign: "middle",
    fontFace: TITLE_FONT, fontSize: 20, bold: true, color: INK,
  });
  s.addText("Nihar Shah", {
    x: cx + 1.35, y: cy + 0.42, w: cw - 1.6, h: 0.35, margin: 0,
    fontFace: TITLE_FONT, fontSize: 18, bold: true, color: BODY,
  });
  s.addText("Design & development — individual project", {
    x: cx + 1.35, y: cy + 0.78, w: cw - 1.6, h: 0.28, margin: 0,
    fontFace: BODY_FONT, fontSize: 11.5, color: MUTED,
  });
  s.addText([
    { text: "Architecture, environment & supervisor implementation", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Fault injection, detectors & recovery controller", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Experiment matrix, evaluation & dashboard", options: { bullet: { code: "2022", indent: 12 } } },
  ], {
    x: cx + 0.3, y: cy + 1.4, w: cw - 0.6, h: 1.1, margin: 0,
    fontFace: BODY_FONT, fontSize: 11.5, color: BODY, paraSpaceAfter: 6,
  });

  // project at a glance card
  const gx = 5.15, gy = 1.7, gw = 4.3, gh = 2.7;
  s.addShape(pres.shapes.RECTANGLE, {
    x: gx, y: gy, w: gw, h: gh, fill: { color: INK }, line: { color: INK },
    shadow: { type: "outer", color: "0A2E2A", blur: 8, offset: 2, angle: 90, opacity: 0.12 },
  });
  s.addText("PROJECT AT A GLANCE", {
    x: gx + 0.3, y: gy + 0.22, w: gw - 0.6, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9.5, charSpacing: 2, color: MINT, bold: true,
  });
  const glance = [
    ["Domain", "LLM agents · tool-use reliability · MCP"],
    ["Duration", "12-week phased plan"],
    ["Evaluation", "120-run deterministic experiment"],
    ["Deliverable", "Working supervisor, dashboard & report"],
  ];
  glance.forEach(([k, v], i) => {
    s.addText(k.toUpperCase(), {
      x: gx + 0.3, y: gy + 0.62 + i * 0.5, w: 1.15, h: 0.24, margin: 0,
      fontFace: MONO_FONT, fontSize: 8.5, color: MUTED_DARK,
    });
    s.addText(v, {
      x: gx + 1.5, y: gy + 0.56 + i * 0.5, w: gw - 1.8, h: 0.34, margin: 0,
      fontFace: BODY_FONT, fontSize: 11.5, color: "FFFFFF",
    });
  });
}

// ============================================================
// S4 — IDEA / APPROACH
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "03 // IDEA & APPROACH", "A supervisor between the agent and its tools");
  footer(s);

  const rows = [
    ["Supervisory MCP facade", "Every tool call is recorded, stamped in logical time, and mediated before it touches the world."],
    ["Transactional operation ledger", "Each write commits with a fingerprint in the same transaction — “did it execute?” is always answerable."],
    ["Detectors", "Repetition, stagnation, unknown commits, and premature completion — grounded in real state, not vibes."],
    ["Bounded recovery", "Substitute verified results, retry only what never ran, block duplicates, reject false “done”."],
  ];
  rows.forEach(([h, d], i) => {
    const y = 1.62 + i * 0.88;
    s.addShape(pres.shapes.OVAL, { x: MX, y: y + 0.05, w: 0.4, h: 0.4, fill: { color: TEAL } });
    s.addText(String(i + 1), {
      x: MX, y: y + 0.05, w: 0.4, h: 0.4, margin: 0, align: "center", valign: "middle",
      fontFace: TITLE_FONT, fontSize: 14, bold: true, color: "FFFFFF",
    });
    s.addText(h, {
      x: MX + 0.58, y, w: 4.3, h: 0.28, margin: 0,
      fontFace: TITLE_FONT, fontSize: 13.5, bold: true, color: BODY,
    });
    s.addText(d, {
      x: MX + 0.58, y: y + 0.28, w: 4.3, h: 0.52, margin: 0,
      fontFace: BODY_FONT, fontSize: 10.5, color: MUTED,
    });
  });

  // comparison card
  const cx = 5.6, cy = 1.55, cw = 3.85, ch = 3.55;
  s.addShape(pres.shapes.RECTANGLE, {
    x: cx, y: cy, w: cw, h: ch, fill: { color: CARD }, line: { color: BORDER, width: 1 },
    shadow: { type: "outer", color: "0A2E2A", blur: 8, offset: 2, angle: 90, opacity: 0.10 },
  });
  s.addText("THE SAME TIMEOUT, TWO OUTCOMES", {
    x: cx + 0.25, y: cy + 0.18, w: cw - 0.5, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9, charSpacing: 1.5, color: MUTED, bold: true,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: cx + 0.25, y: cy + 0.55, w: cw - 0.5, h: 1.25, fill: { color: DANGER_BG } });
  s.addText([
    { text: "B — blind retry", options: { bold: true, color: DANGER, breakLine: true } },
    { text: "Timeout on a committed write → automatic retry → duplicate booking.", options: { color: BODY } },
  ], {
    x: cx + 0.45, y: cy + 0.68, w: cw - 0.9, h: 1.0, margin: 0,
    fontFace: BODY_FONT, fontSize: 11, paraSpaceAfter: 4,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: cx + 0.25, y: cy + 2.0, w: cw - 0.5, h: 1.35, fill: { color: "E4F6EF" } });
  s.addText([
    { text: "C — LoopMedic", options: { bold: true, color: TEAL, breakLine: true } },
    { text: "Same timeout → check ledger → write committed → return the verified result. Duplicate blocked.", options: { color: BODY } },
  ], {
    x: cx + 0.45, y: cy + 2.13, w: cw - 0.9, h: 1.1, margin: 0,
    fontFace: BODY_FONT, fontSize: 11, paraSpaceAfter: 4,
  });
}

// ============================================================
// S5 — PROCESS FLOWCHART
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "04 // PROCESS FLOW", "How a run flows");
  footer(s);

  const boxY = 1.95, boxH = 0.95, subY = 3.85, subH = 0.9;
  const boxOpts = (extra) => ({
    y: boxY, h: boxH, margin: 0, align: "center", valign: "middle",
    fontFace: BODY_FONT, fontSize: 10.5, color: BODY,
    fill: { color: CARD }, line: { color: TEAL, width: 1.25 }, ...extra,
  });

  // start node
  s.addText("User\ntask", {
    x: 0.5, y: boxY + 0.08, w: 1.05, h: 0.8, margin: 0, align: "center", valign: "middle",
    fontFace: BODY_FONT, fontSize: 10.5, color: BODY,
    shape: pres.shapes.OVAL, fill: { color: "E4F6EF" }, line: { color: MINT, width: 1.25 },
  });

  s.addText([
    { text: "Agent runner", options: { bold: true, breakLine: true } },
    { text: "OpenAI Agents SDK", options: { fontSize: 8.5, color: MUTED } },
  ], boxOpts({ x: 1.95, w: 1.6 }));

  s.addText([
    { text: "Supervisory MCP facade", options: { bold: true, breakLine: true } },
    { text: "record · seeded faults · policy", options: { fontSize: 8.5, color: MUTED } },
  ], boxOpts({ x: 3.95, w: 1.95, fill: { color: "E4F6EF" }, line: { color: MINT, width: 1.25 } }));

  s.addText([
    { text: "Appointment service", options: { bold: true, breakLine: true } },
    { text: "SQLite · logical clock · ledger", options: { fontSize: 8.5, color: MUTED } },
  ], boxOpts({ x: 6.3, w: 1.9 }));

  // main chain arrows
  arrow(s, 1.58, boxY + 0.48, 0.34, 0, TEAL);
  arrow(s, 3.58, boxY + 0.48, 0.34, 0, TEAL);
  arrow(s, 5.93, boxY + 0.48, 0.34, 0, TEAL);
  arrowLabel(s, "tool call (MCP)", 4.02, boxY - 0.22, 1.8, MUTED);
  arrowLabel(s, "in-process", 6.28, boxY - 0.22, 1.95, MUTED);

  // sub row: snapshot box + LoopMedic core
  s.addText([
    { text: "Snapshot + state hash", options: { bold: true, breakLine: true } },
    { text: "after every call", options: { fontSize: 8.5, color: MUTED } },
  ], {
    x: 6.3, y: subY, w: 1.9, h: subH, margin: 0, align: "center", valign: "middle",
    fontFace: BODY_FONT, fontSize: 10.5, color: BODY,
    fill: { color: CARD }, line: { color: MINT, width: 1.25 },
  });

  s.addText([
    { text: "LoopMedic core", options: { bold: true, breakLine: true } },
    { text: "ledger · detectors → recovery", options: { fontSize: 8.5, color: LIGHT_TEXT } },
  ], {
    x: 3.95, y: subY, w: 1.95, h: subH, margin: 0, align: "center", valign: "middle",
    fontFace: BODY_FONT, fontSize: 10.5, color: "FFFFFF",
    fill: { color: INK }, line: { color: INK },
  });

  // service -> snapshot, snapshot -> core
  arrow(s, 7.25, boxY + boxH + 0.03, 0, subY - boxY - boxH - 0.06, MINT);
  arrow(s, 6.27, subY + 0.45, -(6.27 - 5.93), 0, MINT);

  // facade <-> core (two one-way arrows)
  arrow(s, 4.5, boxY + boxH + 0.03, 0, subY - boxY - boxH - 0.06, TEAL);
  arrow(s, 5.35, subY - 0.03, 0, -(subY - boxY - boxH - 0.06), MINT);
  arrowLabel(s, "proposed call", 3.28, 3.32, 1.2, MUTED);
  arrowLabel(s, "allow · block · verified", 5.42, 3.32, 1.6, MUTED);

  // dashed lifecycle hooks: agent runner -> core
  arrow(s, 2.75, boxY + boxH + 0.03, 1.35, subY - boxY - boxH - 0.1, MUTED, true);
  arrowLabel(s, "lifecycle hooks", 1.7, 3.32, 1.3, MUTED);

  s.addText("Every run: fresh seeded database · logical clock · 15-call cap · full trace", {
    x: MX, y: 5.0, w: 8.9, h: 0.25, margin: 0, align: "center",
    fontFace: MONO_FONT, fontSize: 9, color: TEAL,
  });
}

// ============================================================
// S6 — EVALUATION
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "05 // EVALUATION", "Measured, not vibes");
  footer(s);

  const stats = [["120", "runs"], ["20", "scenarios"], ["3", "conditions"], ["4", "fault types"]];
  stats.forEach(([n, label], i) => {
    const x = MX + i * 1.32;
    s.addText(n, {
      x, y: 1.65, w: 1.2, h: 0.62, margin: 0,
      fontFace: TITLE_FONT, fontSize: 34, bold: true, color: TEAL,
    });
    s.addText(label.toUpperCase(), {
      x, y: 2.3, w: 1.2, h: 0.22, margin: 0,
      fontFace: MONO_FONT, fontSize: 8.5, charSpacing: 1, color: MUTED,
    });
  });

  s.addText([
    { text: "12 faulted + 8 clean scenarios × { A: no supervision, B: blind retry, C: LoopMedic } × 2 repetitions.", options: { breakLine: true } },
    { text: "Conditions matched on scenario and fault seed; fresh database per run.", options: { color: MUTED, breakLine: true } },
    { text: "Model: kimi-k2.7-code via OpenCode Go (Chat Completions).", options: { color: MUTED } },
  ], {
    x: MX, y: 2.7, w: 5.1, h: 1.05, margin: 0,
    fontFace: BODY_FONT, fontSize: 12, color: BODY, paraSpaceAfter: 5,
  });

  s.addText("Judged by deterministic database invariants — final-state and history-based — never by an LLM judge.", {
    x: MX, y: 3.95, w: 5.1, h: 0.75, margin: 0.12,
    fontFace: BODY_FONT, fontSize: 12, italic: true, color: INK,
    fill: { color: "E4F6EF" }, line: { color: MINT, width: 1 }, valign: "middle",
  });

  // metrics card
  const cx = 6.0, cy = 1.6, cw = 3.45, ch = 3.4;
  s.addShape(pres.shapes.RECTANGLE, {
    x: cx, y: cy, w: cw, h: ch, fill: { color: CARD }, line: { color: BORDER, width: 1 },
    shadow: { type: "outer", color: "0A2E2A", blur: 8, offset: 2, angle: 90, opacity: 0.10 },
  });
  s.addText("METRICS", {
    x: cx + 0.25, y: cy + 0.2, w: cw - 0.5, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9.5, charSpacing: 2, color: TEAL, bold: true,
  });
  s.addText([
    { text: "Task success rate", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Safety-violation rate (history invariants)", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Recovery rate: A-failing runs C saves", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Clean-run impact of interventions", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Duplicate writes prevented", options: { bullet: { code: "2022", indent: 12 }, breakLine: true } },
    { text: "Tool calls & tokens per run", options: { bullet: { code: "2022", indent: 12 } } },
  ], {
    x: cx + 0.25, y: cy + 0.55, w: cw - 0.5, h: 2.7, margin: 0,
    fontFace: BODY_FONT, fontSize: 11.5, color: BODY, paraSpaceAfter: 8,
  });
}

// ============================================================
// S7 — TECHNOLOGY STACK
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: BG };
  header(s, "06 // TECHNOLOGY STACK", "Deliberately boring, fully reproducible");
  footer(s);

  const cards = [
    ["Py", "Python 3.12", "one subprocess per run, single event loop"],
    ["Ag", "OpenAI Agents SDK", "agent runner + lifecycle hooks"],
    ["Go", "OpenCode Go", "models via Chat Completions — kimi-k2.7-code default"],
    ["MC", "MCP 2.0", "streamable-HTTP tool protocol"],
    ["SQ", "SQLite (stdlib)", "world state + operation ledger"],
    ["Pd", "Pydantic", "events, configs & schemas"],
    ["pt", "pytest", "scripted, LLM-free proofs of every demo"],
    ["Re", "React viewer", "custom dashboard — final phase only"],
  ];
  cards.forEach(([mono, name, role], i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = MX + col * 2.26, y = 1.65 + row * 1.62, w = 2.12, h = 1.45;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h, fill: { color: CARD }, line: { color: BORDER, width: 1 },
      shadow: { type: "outer", color: "0A2E2A", blur: 6, offset: 2, angle: 90, opacity: 0.08 },
    });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.18, y: y + 0.18, w: 0.42, h: 0.42, fill: { color: "E4F6EF" } });
    s.addText(mono, {
      x: x + 0.18, y: y + 0.18, w: 0.42, h: 0.42, margin: 0, align: "center", valign: "middle",
      fontFace: MONO_FONT, fontSize: 12, bold: true, color: TEAL,
    });
    s.addText(name, {
      x: x + 0.18, y: y + 0.68, w: w - 0.36, h: 0.26, margin: 0,
      fontFace: TITLE_FONT, fontSize: 12.5, bold: true, color: BODY,
    });
    s.addText(role, {
      x: x + 0.18, y: y + 0.94, w: w - 0.36, h: 0.44, margin: 0,
      fontFace: BODY_FONT, fontSize: 9, color: MUTED,
    });
  });

  s.addText("YAML scenario configs · explicit seeds everywhere · no Docker · no microservices · no LLM judges", {
    x: MX, y: 5.0, w: 8.9, h: 0.25, margin: 0, align: "center",
    fontFace: MONO_FONT, fontSize: 9.5, color: TEAL,
  });
}

// ============================================================
// S8 — STATUS & ROADMAP (dark)
// ============================================================
{
  const s = pres.addSlide();
  s.background = { color: INK };
  header(s, "07 // WHERE WE ARE", "Foundation proven; build-out in phases", true);

  s.addText("PROVEN IN WEEK 1", {
    x: MX, y: 1.6, w: 4.2, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9.5, charSpacing: 2, color: MINT, bold: true,
  });
  const done = [
    "Deterministic seeded database — byte-identical per seed",
    "Completion-rejection via SDK output guardrails, run continues",
    "MCP streamable-HTTP transport in a single process",
    "5/5 tests green — spikes scripted, no API key needed",
  ];
  done.forEach((t, i) => {
    const y = 1.95 + i * 0.62;
    s.addShape(pres.shapes.RECTANGLE, { x: MX, y: y + 0.06, w: 0.16, h: 0.16, fill: { color: MINT } });
    s.addText(t, {
      x: MX + 0.32, y, w: 4.1, h: 0.58, margin: 0,
      fontFace: BODY_FONT, fontSize: 11, color: LIGHT_TEXT,
    });
  });

  s.addText("NEXT PHASES", {
    x: 5.3, y: 1.6, w: 4.2, h: 0.24, margin: 0,
    fontFace: MONO_FONT, fontSize: 9.5, charSpacing: 2, color: MINT, bold: true,
  });
  const phases = [
    ["P1–P2", "Environment, evaluator, Go tool-call spike & baseline agent"],
    ["P3–P5", "Tracing, state hash, facade & fault injection"],
    ["P6–P7", "Detectors & recovery controller"],
    ["P8–P10", "120-run matrix → custom viewer → report & demo"],
  ];
  phases.forEach(([p, d], i) => {
    const y = 1.95 + i * 0.62;
    s.addText(p, {
      x: 5.3, y, w: 0.85, h: 0.3, margin: 0,
      fontFace: MONO_FONT, fontSize: 10, bold: true, color: MINT,
    });
    s.addText(d, {
      x: 6.2, y, w: 3.3, h: 0.55, margin: 0,
      fontFace: BODY_FONT, fontSize: 11, color: LIGHT_TEXT,
    });
  });

  s.addText("LoopMedic — let agents act, under supervision.", {
    x: MX, y: 4.85, w: 8.9, h: 0.35, margin: 0, align: "center",
    fontFace: BODY_FONT, fontSize: 14, italic: true, color: MINT,
  });
}

pres.writeFile({ fileName: "/Users/niharshah/Downloads/LoopMedic-Proposal.pptx" }).then(() => console.log("written"));
