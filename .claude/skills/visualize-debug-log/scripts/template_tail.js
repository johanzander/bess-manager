
const INTENT_COLOR = {
  LOAD_SUPPORT: 'var(--c-load)',
  SOLAR_STORAGE: 'var(--c-solar-store)',
  SOLAR_EXPORT: 'var(--c-solar-export)',
  GRID_CHARGING: 'var(--c-grid-charge)',
  BATTERY_EXPORT: 'var(--c-export)',
  IDLE: 'var(--c-idle)',
};
const INTENT_ORDER = ['SOLAR_STORAGE', 'SOLAR_EXPORT', 'BATTERY_EXPORT', 'LOAD_SUPPORT', 'GRID_CHARGING', 'IDLE'];
const CYCLE_COST = SUMMARY.cycle_cost;

// Price-panel series — all independently toggleable. shadow/cost-basis/breakeven are
// "gapped" (only populated for forecast periods, so the line breaks rather than
// dropping to zero across the actual/historical morning).
const PRICE_SERIES = [
  { key: 'sell', label: 'Sell price', def: 'What exporting to the grid earns per kWh, right now.', color: 'var(--sell-line)', get: r => r.sell, panel: 'price', defaultOn: true },
  { key: 'buy', label: 'Buy price', def: 'What importing from the grid costs per kWh, right now.', color: 'var(--buy-line)', get: r => r.buy, panel: 'price', defaultOn: true, dashed: true },
  { key: 'shadow', label: 'Shadow price', def: "The optimizer's own marginal value of one more kWh in the battery right now — a genuine decision input (see Why in the tooltip).", color: 'var(--c-shadow)', get: r => r.shadow_price, panel: 'price', defaultOn: false, gapped: true },
  { key: 'costbasis', label: 'Cost basis (stored energy)', def: 'Acquisition cost: the weighted-average price paid per kWh of energy currently stored. Retrospective only — never affects the decision (see Outcome in the tooltip).', color: 'var(--c-solar-flow)', get: r => r.cost_basis, panel: 'price', defaultOn: false, gapped: true },
  { key: 'breakeven', label: 'Breakeven (cost basis + cycle cost)', def: 'Cost basis plus battery wear cost — the price a discharge must clear to be profitable, by this retrospective accounting. Also never affects the decision (see Outcome in the tooltip).', color: 'var(--c-solar-store)', get: r => r.cost_basis > 0 ? r.cost_basis + CYCLE_COST : 0, panel: 'price', defaultOn: false, gapped: true, dashed: true },
];
// Energy Trend series — Growatt-app style: six independently toggleable overlaid series.
const ENERGY_SERIES = [
  { key: 'export', label: 'Exported to Grid', def: 'kWh sold to the grid this period (solar surplus + battery discharge).', color: 'var(--s-export)', get: r => r.solar_to_grid + r.batt_to_grid, panel: 'energy', defaultOn: true },
  { key: 'pv', label: 'Photovoltaic Output', def: 'Total solar production this period, before any allocation.', color: 'var(--s-pv)', get: r => r.solar, panel: 'energy', defaultOn: true },
  { key: 'dis', label: 'Discharging', def: 'kWh leaving the battery this period, to home or grid.', color: 'var(--s-dis)', get: r => r.batt_to_home + r.batt_to_grid, panel: 'energy', defaultOn: true },
  { key: 'imp', label: 'Imported From Grid', def: 'kWh bought from the grid this period, for home or battery.', color: 'var(--s-imp)', get: r => r.grid_to_home + r.grid_to_batt, panel: 'energy', defaultOn: true },
  { key: 'chg', label: 'Charging', def: 'kWh entering the battery this period, from solar or grid.', color: 'var(--s-chg)', get: r => r.solar_to_batt + r.grid_to_batt, panel: 'energy', defaultOn: true },
  { key: 'load', label: 'Load Consumption', def: 'Total home electricity use this period.', color: 'var(--s-load)', get: r => r.load, panel: 'energy', defaultOn: true },
];
const ALL_SERIES = [...PRICE_SERIES, ...ENERGY_SERIES];
const activeSeries = new Set(ALL_SERIES.filter(s => s.defaultOn).map(s => s.key));

// ---- stats: whole-trace economic summary, from each period's own economic data ----
const stats = document.getElementById('stats');
const oreOf = (v) => Math.round(v * 100);
const savingsPct = SUMMARY.grid_only_cost ? (SUMMARY.savings / SUMMARY.grid_only_cost) * 100 : 0;
stats.innerHTML = `
  <div class="stat"><div class="label">Grid-only cost</div><div class="value">${SUMMARY.grid_only_cost.toFixed(2)} SEK</div><div class="sub">baseline, no solar/battery</div></div>
  <div class="stat"><div class="label">Actual cost</div><div class="value">${SUMMARY.actual_cost.toFixed(2)} SEK</div><div class="sub">with solar + battery</div></div>
  <div class="stat margin ${SUMMARY.savings >= 0 ? 'positive' : ''}"><div class="label">Savings</div><div class="value">${SUMMARY.savings >= 0 ? '+' : ''}${SUMMARY.savings.toFixed(2)} SEK</div><div class="sub">${savingsPct.toFixed(0)}% of grid-only cost</div></div>
  <div class="stat"><div class="label">Cycle cost</div><div class="value">${oreOf(CYCLE_COST)} öre/kWh</div><div class="sub">config: cycle_cost_per_kwh</div></div>
  <div class="stat"><div class="label">Battery capacity</div><div class="value">${SUMMARY.capacity} kWh</div><div class="sub">${SUMMARY.n_actual} actual + ${SUMMARY.n_forecast} forecast periods</div></div>
`;

// ---- legend: one ledger, every line individually toggleable ----
const legend = document.getElementById('legend');
function seriesButton(s) {
  const off = !activeSeries.has(s.key) ? ' off' : '';
  return `<button type="button" class="swatch${off}" data-key="${s.key}" title="${s.def}"><span class="dot" style="background:${s.color}"></span>${s.label}</button>`;
}
const priceButtons = PRICE_SERIES.map(seriesButton).join('');
const energyButtons = ENERGY_SERIES.map(seriesButton).join('');
// Not a line/point series (draws a rect pair per discharging period, not a
// path) -- own toggle button + group, kept out of ALL_SERIES so the generic
// line-drawing and hover-dot code don't try to treat it as one.
const PROFIT_TOGGLE = { key: 'profit', label: 'Profit areas', def: 'Shaded per-period brackets: buy/sell price vs. breakeven, sized by the actual profit (see tooltip for the number).', color: 'var(--c-load)' };
const profitButton = seriesButton(PROFIT_TOGGLE);
const INTENT_DEF = {
  SOLAR_STORAGE: 'Charging the battery from solar surplus.',
  SOLAR_EXPORT: 'Solar surplus sold to the grid; battery untouched.',
  BATTERY_EXPORT: 'Discharging with some or all going to the grid.',
  LOAD_SUPPORT: 'Discharging to cover home load only, nothing exported.',
  GRID_CHARGING: 'Charging the battery from the grid.',
  IDLE: 'No beneficial battery action this period.',
};
const intentSwatches = INTENT_ORDER.map(k =>
  `<span class="swatch" title="${INTENT_DEF[k]}"><span class="dot" style="background:${INTENT_COLOR[k]}"></span>${k}</span>`
).join('');

// ---- glossary: short definition for every term, grouped by category so a
// mix of prices/energies/states doesn't read as one flat, unordered list ----
const glossary = document.getElementById('glossary');
function glossEntry(label, color, def) {
  return `<div><dt>${color ? `<span class="dot" style="background:${color}"></span>` : ''}${label}</dt><dd>${def}</dd></div>`;
}
function glossHeader(text) {
  return `<div class="section-header">${text}</div>`;
}
glossary.innerHTML = [
  glossHeader('Price'),
  ...PRICE_SERIES.map(s => glossEntry(s.label, s.color, s.def)),
  glossEntry(PROFIT_TOGGLE.label, null, PROFIT_TOGGLE.def),
  glossHeader('Energy'),
  ...ENERGY_SERIES.map(s => glossEntry(s.label, s.color, s.def)),
  glossHeader('Battery'),
  glossEntry('SOE', null, 'Battery State of Energy, in kWh — this system tracks charge as an energy quantity, not a percentage.'),
  glossHeader('Decision'),
  glossEntry('Total value', null, "The winning candidate action's score: reward + future value. The optimizer tries every candidate action this period (idle, several discharge levels, one charge option) and picks whichever scores highest on this sum."),
  glossEntry('Reward', null, "This period's own grid cost/revenue for the chosen action (export revenue &minus; import cost &minus; battery wear) — one of total value's two components."),
  glossEntry('Future value', null, "The precomputed best-achievable outcome from the resulting battery level onward — total value's other component. Shadow price is this same table's local slope, not a separate ingredient."),
  glossHeader('Intent'),
  glossEntry('Background tint', null, "The optimizer's intent label for that period (hover an intent name in the legend below for its meaning)."),
].join('');

// ---- ledger: same grouping, one labeled row per category, own toggles ----
function legendGroup(label, contentHtml) {
  return `<span class="group-label">${label}</span><span class="group">${contentHtml}</span><span class="group-sep"></span>`;
}
legend.innerHTML =
  legendGroup('Price', `${priceButtons}${profitButton}`) +
  legendGroup('Energy', energyButtons) +
  legendGroup('Intent', `${intentSwatches}<span class="swatch" style="opacity:0.75">(background tint)</span>`);

legend.querySelectorAll('button.swatch[data-key]').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key;
    if (activeSeries.has(key)) { activeSeries.delete(key); btn.classList.add('off'); }
    else { activeSeries.add(key); btn.classList.remove('off'); }
    const g = document.getElementById(`series-${key}`);
    if (g) g.classList.toggle('series-hidden', !activeSeries.has(key));
    const dot = document.getElementById(`hoverDot-${key}`);
    if (dot && !activeSeries.has(key)) dot.style.opacity = 0;
    if (lastHoverIdx !== null) renderTooltip(lastHoverIdx);
  });
});

// ---- table ----
const tbody = document.getElementById('tbody');
tbody.innerHTML = ROWS.map(r => `<tr>
  <td class="time">${r.time}</td>
  <td style="text-align:right;color:${INTENT_COLOR[r.intent]}">${r.intent}</td>
  <td>${r.buy.toFixed(2)}</td>
  <td>${r.sell.toFixed(2)}</td>
  <td>${r.solar.toFixed(2)}</td>
  <td>${r.load.toFixed(2)}</td>
  <td>${r.solar_to_home.toFixed(2)}</td>
  <td>${r.solar_to_batt.toFixed(2)}</td>
  <td>${r.solar_to_grid.toFixed(2)}</td>
  <td>${r.grid_to_batt.toFixed(2)}</td>
  <td>${r.batt_to_home.toFixed(2)}</td>
  <td>${r.batt_to_grid.toFixed(2)}</td>
  <td>${r.soe_start.toFixed(2)}</td>
  <td>${r.soe_end.toFixed(2)}</td>
  <td>${(r.soe_end - r.soe_start >= 0 ? '+' : '')}${(r.soe_end - r.soe_start).toFixed(2)}</td>
  <td>${r.source}</td>
</tr>`).join('');

// ---- chart: three stacked panels (price, energy trend, SOE) sharing one x-scale ----
const W = 920;
const PAD = { top: 22, right: 16, bottom: 30, left: 44 };
const PRICE_H = 190, ENERGY_H = 170, SOE_H = 90, GAP = 8, TITLE_H = 20;
const n = ROWS.length;
const x = (i) => PAD.left + (i / (n - 1)) * (W - PAD.left - PAD.right);
const plotW = W - PAD.left - PAD.right;

const priceTop = PAD.top, priceBottom = priceTop + PRICE_H;
const energyTop = priceBottom + GAP + TITLE_H, energyBottom = energyTop + ENERGY_H;
const soeTop = energyBottom + GAP + TITLE_H, soeBottom = soeTop + SOE_H;
const totalH = soeBottom + PAD.bottom;

const priceMax = Math.max(...ROWS.map(r => r.buy)) * 1.08;
const yPrice = (v) => priceTop + PRICE_H - (v / priceMax) * PRICE_H;

const energyMax = Math.max(...ROWS.map(r => Math.max(...ENERGY_SERIES.map(s => s.get(r))))) * 1.15;
const yEnergy = (v) => energyTop + ENERGY_H - (v / energyMax) * ENERGY_H;

const soeCapacity = Math.ceil(Math.max(...ROWS.map(r => Math.max(r.soe_start, r.soe_end))) / 5) * 5;
const ySoe = (v) => soeTop + SOE_H - (v / soeCapacity) * SOE_H;

function yFor(panel) { return panel === 'price' ? yPrice : yEnergy; }

function pathFor(panelY, getter) {
  return ROWS.map((r, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(2)} ${panelY(getter(r)).toFixed(2)}`).join(' ');
}
function areaFor(panelY, getter, zeroY) {
  const line = pathFor(panelY, getter);
  return `${line} L ${x(n - 1).toFixed(2)} ${zeroY.toFixed(2)} L ${x(0).toFixed(2)} ${zeroY.toFixed(2)} Z`;
}
// Path with gaps: breaks the line wherever getter(r) isn't a real positive value
// (used for shadow_price/cost_basis/breakeven, which are only populated for forecast periods).
function gappedPathFor(panelY, getter) {
  let d = '';
  let drawing = false;
  ROWS.forEach((r, i) => {
    const v = getter(r);
    if (v > 0) {
      d += `${drawing ? 'L' : 'M'} ${x(i).toFixed(2)} ${panelY(v).toFixed(2)} `;
      drawing = true;
    } else {
      drawing = false;
    }
  });
  return d;
}

// stepped SOE path: soe_start at left edge of period, soe_end at right edge
function soeStepPath() {
  let d = `M ${x(0).toFixed(2)} ${ySoe(ROWS[0].soe_start).toFixed(2)}`;
  ROWS.forEach((r, i) => {
    d += ` L ${x(i).toFixed(2)} ${ySoe(r.soe_end).toFixed(2)}`;
    if (i < n - 1) d += ` L ${x(i + 1).toFixed(2)} ${ySoe(ROWS[i + 1].soe_start).toFixed(2)}`;
  });
  return d;
}
function soeAreaPath() {
  const line = soeStepPath();
  return `${line} L ${x(n - 1).toFixed(2)} ${ySoe(0).toFixed(2)} L ${x(0).toFixed(2)} ${ySoe(0).toFixed(2)} Z`;
}

const priceYTicks = [];
for (let p = 0; p <= priceMax; p += 0.5) priceYTicks.push(+p.toFixed(2));
const energyYTicks = [0, +(energyMax / 2).toFixed(1), +energyMax.toFixed(1)];
const soeYTicks = [0, soeCapacity / 2, soeCapacity];

// One tick every 4 hours (16 periods @ 15min), plus the final period.
const xTickIdx = [];
for (let i = 0; i < n; i += 16) xTickIdx.push(i);
if (xTickIdx[xTickIdx.length - 1] !== n - 1) xTickIdx.push(n - 1);

// per-period background segment width (half-open, centered on sample)
const segW = plotW / n;
function bgRects(topY, h) {
  return ROWS.map((r, i) =>
    `<rect class="intent-bg" x="${(x(i) - segW / 2).toFixed(2)}" y="${topY}" width="${(segW + 0.6).toFixed(2)}" height="${h}" fill="${INTENT_COLOR[r.intent]}"/>`
  ).join('');
}

let svg = `<svg viewBox="0 0 ${W} ${totalH}" role="img" aria-label="Price (sell, buy, shadow price, cost basis, breakeven), toggleable energy trend, and battery state of charge, background tinted by optimizer intent per period">`;

// panel titles
svg += `<text class="panel-title" x="${PAD.left}" y="${priceTop - 8}">Price (SEK/kWh) &mdash; click a line in the legend to show/hide it</text>`;
svg += `<text class="panel-title" x="${PAD.left}" y="${energyTop - 8}">Energy Trend (kWh / 15 min)</text>`;
svg += `<text class="panel-title" x="${PAD.left}" y="${soeTop - 8}">Battery SOE (kWh)</text>`;

// ---- price panel ----
svg += bgRects(priceTop, PRICE_H);
for (const t of priceYTicks) {
  svg += `<line class="gridline" x1="${PAD.left}" x2="${W - PAD.right}" y1="${yPrice(t)}" y2="${yPrice(t)}"/>`;
  svg += `<text class="axis-label" x="${PAD.left - 8}" y="${yPrice(t) + 3}" text-anchor="end">${t.toFixed(1)}</text>`;
}
PRICE_SERIES.forEach(s => {
  const hidden = activeSeries.has(s.key) ? '' : ' series-hidden';
  const path = s.gapped ? gappedPathFor(yPrice, s.get) : pathFor(yPrice, s.get);
  const dash = s.dashed ? ' stroke-dasharray="4 3"' : '';
  svg += `<g class="series-group${hidden}" id="series-${s.key}">` +
    `<path class="series-line" style="stroke:${s.color}"${dash} d="${path}"/>` +
    `</g>`;
});
const lastI = n - 1;
svg += `<text class="direct-label" x="${x(lastI) + 6}" y="${yPrice(ROWS[lastI].sell) + 3}" fill="var(--sell-line)">sell</text>`;
svg += `<text class="direct-label" x="${x(lastI) + 6}" y="${yPrice(ROWS[lastI].buy) + 3}" fill="var(--buy-line)">buy</text>`;
// Day boundary markers (00:00), generic to however many days the trace spans.
const dayBoundaries = ROWS.map((r, i) => ({ r, i })).filter(({ r }) => r.time === '00:00' && r.period > 0);
dayBoundaries.forEach(({ i }, dayNum) => {
  svg += `<line class="ref-line" x1="${x(i)}" x2="${x(i)}" y1="${priceTop}" y2="${soeBottom}" stroke-dasharray="1 4"/>`;
  svg += `<text class="ref-label" x="${x(i) + 4}" y="${priceTop + 10}">day ${dayNum + 2} &rarr;</text>`;
});

// ---- Profit areas: every discharge period, not just one example ----
// Two brackets per period, same breakeven reference as the tooltip's profit
// rows: home-serving profit priced at buy price (what it avoided), export
// profit priced at sell price (what it earned). Bracket height = per-kWh
// margin × that period's column width -- hover for the exact SEK figure
// (already in the tooltip's DP-reasoning section). Off by default (one rect
// pair per discharging period can get busy); toggle in the ledger.
const profitBarW = Math.max(1.5, segW * 0.7);
let profitAreasSvg = '';
ROWS.forEach((r, i) => {
  const v = r.view;
  if (v.breakeven === null) return;
  const px = x(i);
  const yBreakeven = yPrice(v.breakeven);
  if (v.home_profit !== null) {
    const yBuy = yPrice(r.buy);
    profitAreasSvg += `<rect x="${(px - profitBarW / 2).toFixed(2)}" y="${Math.min(yBuy, yBreakeven).toFixed(2)}" width="${profitBarW.toFixed(2)}" height="${Math.abs(yBreakeven - yBuy).toFixed(2)}" fill="var(--c-load)" opacity="0.35"/>`;
  }
  if (v.export_profit !== null) {
    const ySell = yPrice(r.sell);
    profitAreasSvg += `<rect x="${(px - profitBarW / 2).toFixed(2)}" y="${Math.min(ySell, yBreakeven).toFixed(2)}" width="${profitBarW.toFixed(2)}" height="${Math.abs(yBreakeven - ySell).toFixed(2)}" fill="var(--c-export)" opacity="0.35"/>`;
  }
});
const profitHidden = activeSeries.has('profit') ? '' : ' series-hidden';
svg += `<g class="series-group${profitHidden}" id="series-profit">${profitAreasSvg}</g>`;

// ---- energy trend panel (six overlaid, independently toggleable series) ----
svg += bgRects(energyTop, ENERGY_H);
for (const t of energyYTicks) {
  svg += `<line class="gridline" x1="${PAD.left}" x2="${W - PAD.right}" y1="${yEnergy(t)}" y2="${yEnergy(t)}"/>`;
  svg += `<text class="axis-label" x="${PAD.left - 8}" y="${yEnergy(t) + 3}" text-anchor="end">${t}</text>`;
}
const energyZeroY = yEnergy(0);
ENERGY_SERIES.forEach(s => {
  const hidden = activeSeries.has(s.key) ? '' : ' series-hidden';
  svg += `<g class="series-group${hidden}" id="series-${s.key}">` +
    `<path class="series-area" style="fill:${s.color}" d="${areaFor(yEnergy, s.get, energyZeroY)}"/>` +
    `<path class="series-line" style="stroke:${s.color}" d="${pathFor(yEnergy, s.get)}"/>` +
    `</g>`;
});

// ---- SOE panel ----
svg += bgRects(soeTop, SOE_H);
for (const t of soeYTicks) {
  svg += `<line class="gridline" x1="${PAD.left}" x2="${W - PAD.right}" y1="${ySoe(t)}" y2="${ySoe(t)}"/>`;
  svg += `<text class="axis-label" x="${PAD.left - 8}" y="${ySoe(t) + 3}" text-anchor="end">${t}</text>`;
}
svg += `<path class="soc-area" d="${soeAreaPath()}"/>`;
svg += `<path class="soc-line" d="${soeStepPath()}"/>`;

// x labels (bottom of SOE panel)
for (const i of xTickIdx) {
  svg += `<text class="axis-label" x="${x(i)}" y="${soeBottom + 16}" text-anchor="middle">${ROWS[i].time}</text>`;
}

// hover interaction elements (span all panels)
svg += `<line class="hover-line" id="hoverLine" x1="0" x2="0" y1="${priceTop}" y2="${soeBottom}"/>`;
ALL_SERIES.forEach(s => {
  svg += `<circle class="hover-dot" id="hoverDot-${s.key}" r="3.5" style="fill:${s.color}"/>`;
});
svg += `<circle class="hover-dot" id="hoverDotSoe" r="3.5" fill="var(--text-primary)"/>`;
svg += `<rect id="hoverCapture" x="${PAD.left}" y="${priceTop}" width="${plotW}" height="${soeBottom - priceTop}" fill="transparent"/>`;

svg += `</svg><div class="tooltip" id="tooltip"></div>`;

document.getElementById('chartWrap').innerHTML = svg;

// hover behavior
const wrap = document.getElementById('chartWrap');
const svgEl = wrap.querySelector('svg');
const capture = document.getElementById('hoverCapture');
const hoverLine = document.getElementById('hoverLine');
const seriesDots = Object.fromEntries(ALL_SERIES.map(s => [s.key, document.getElementById(`hoverDot-${s.key}`)]));
const dotSoe = document.getElementById('hoverDotSoe');
const tooltip = document.getElementById('tooltip');
let lastHoverIdx = null;

function svgPoint(evt) {
  const rect = svgEl.getBoundingClientRect();
  const scaleX = W / rect.width;
  return (evt.clientX - rect.left) * scaleX;
}

function renderTooltip(idx) {
  const r = ROWS[idx];
  hoverLine.setAttribute('x1', x(idx)); hoverLine.setAttribute('x2', x(idx));
  hoverLine.style.opacity = 1;
  ALL_SERIES.forEach(s => {
    const dot = seriesDots[s.key];
    dot.setAttribute('cx', x(idx)); dot.setAttribute('cy', yFor(s.panel)(s.get(r)));
    dot.style.opacity = (activeSeries.has(s.key) && s.get(r) > 0) || (activeSeries.has(s.key) && !s.gapped) ? 1 : 0;
  });
  dotSoe.setAttribute('cx', x(idx)); dotSoe.setAttribute('cy', ySoe(r.soe_end)); dotSoe.style.opacity = 1;

  const rect = wrap.getBoundingClientRect();
  const scale = rect.width / W;
  tooltip.style.left = (x(idx) * scale + 10) + 'px';
  tooltip.style.top = (yPrice(Math.max(r.sell, r.buy)) * scale - 8) + 'px';
  tooltip.style.opacity = 1;

  const v = r.view;
  let actionLine, actionColor;
  if (v.charge_total > 0) {
    const parts = v.charge_parts.map(p => `${p.kwh.toFixed(2)} ${p.source}`);
    actionLine = `⚡ +${v.charge_total.toFixed(2)} kWh charge (${parts.join(' + ')})`;
    actionColor = 'var(--s-chg)';
  } else if (v.discharge_total > 0) {
    const parts = v.discharge_parts.map(p => `${p.kwh.toFixed(2)} ${p.source}`);
    actionLine = `⚡ −${v.discharge_total.toFixed(2)} kWh discharge (${parts.join(' + ')})`;
    actionColor = 'var(--s-dis)';
  } else {
    actionLine = 'no battery action';
    actionColor = 'var(--text-muted)';
  }

  // Every row gets the same color dot as its matching chart line/series, so
  // a tooltip value can be traced back to what's drawn without re-reading
  // the legend each time.
  function dotRow(label, value, color) {
    const dot = color ? `<span class="dot" style="background:${color}"></span>` : '<span class="dot" style="background:transparent"></span>';
    return `<div class="t-row"><span>${dot}${label}</span><b>${value}</b></div>`;
  }
  function subRow(text) {
    return `<div class="t-row" style="font-size:10px; opacity:0.75"><span>&nbsp;&nbsp;${text}</span></div>`;
  }

  let priceRows = dotRow('buy', `${r.buy.toFixed(2)} SEK/kWh`, 'var(--buy-line)') +
    dotRow('sell', `${r.sell.toFixed(2)} SEK/kWh`, 'var(--sell-line)');
  if (activeSeries.has('shadow') && r.shadow_price > 0) priceRows += dotRow('shadow price', `${r.shadow_price.toFixed(2)} SEK/kWh`, 'var(--c-shadow)');
  if (activeSeries.has('costbasis') && r.cost_basis > 0) priceRows += dotRow('cost basis (stored energy)', `${r.cost_basis.toFixed(2)} SEK/kWh`, 'var(--c-solar-flow)');
  if (activeSeries.has('breakeven') && r.cost_basis > 0) priceRows += dotRow('breakeven (this period)', `${(r.cost_basis + CYCLE_COST).toFixed(2)} SEK/kWh`, 'var(--c-solar-store)');

  const energyRows = dotRow('PV output', `${r.solar.toFixed(2)} kWh`, 'var(--s-pv)') +
    dotRow('load', `${r.load.toFixed(2)} kWh`, 'var(--s-load)') +
    dotRow('exported to grid', `${v.export_total.toFixed(2)} kWh`, 'var(--s-export)') +
    dotRow('imported from grid', `${v.import_total.toFixed(2)} kWh`, 'var(--s-imp)');

  const batteryRows = dotRow('SOE', `${r.soe_start.toFixed(2)} &rarr; ${r.soe_end.toFixed(2)} kWh`, 'var(--text-primary)') +
    dotRow('SOE &Delta;', `${(r.soe_end - r.soe_start >= 0 ? '+' : '')}${(r.soe_end - r.soe_start).toFixed(2)} kWh`, 'var(--text-primary)');

  // ---- Why: ONLY what genuinely entered the DP's comparison -- price and ----
  // shadow price (the value-to-go readout). Cost basis, breakeven, and the
  // profit-vs-breakeven math below are real numbers but NEVER part of the
  // reward or value-to-go the DP actually maximizes (verified by tracing
  // _compute_reward: cost_basis only updates bookkeeping, never total_cost)
  // -- they belong in Outcome (a retrospective check), not here. Always
  // shown regardless of chart-line toggles: toggles control what's drawn,
  // not what the tooltip is allowed to explain.
  // ---- Decision: shadow price + whichever price is relevant, the plain- ----
  // language read of them, then the actual math -- total value (the winning
  // candidate's score) broken into its two real components, reward broken
  // into its three. The optimizer tries every candidate action this period
  // (idle, several discharge levels, one charge option) and picks whichever
  // scores highest on reward + future value; this is that winner's own
  // breakdown, not a side-by-side vs. the candidates that lost (the debug
  // bundle doesn't record those).
  // Sentence copy keyed by the case Python already decided (compute_decision_view
  // in build_chart.py) -- this layer only picks a template and fills in numbers
  // it's handed, it never re-derives a threshold or a clears/falls-short call.
  const DECISION_SENTENCE = {
    export: c => `Sell price ${c.clears ? 'clears' : 'falls short of'} the optimizer's own marginal value of holding this energy — ${c.clears ? 'a good reason to let it go to the grid now rather than hold for later.' : 'holding a bit longer would likely have been worth more.'}`,
    home: c => `Using this energy now ${c.clears ? 'clears' : 'falls short of'} its own marginal value — ${c.clears ? 'worth spending here rather than saving it.' : 'a close call; saving it a bit longer might have been worth more.'}`,
    grid_charge: c => `Shadow price ${c.clears ? 'clears' : 'falls short of'} the cost of buying and storing this energy (${c.buy.toFixed(2)} buy + ${c.cycle_cost.toFixed(2)} cycle cost) — ${c.clears ? 'worth it.' : 'a marginal call; this charge may lean on other considerations, not this price alone.'}`,
    solar_store: c => `Shadow price ${c.clears ? 'clears' : 'falls short of'} what this solar would earn by exporting right now, plus the cost of storing it (${c.sell.toFixed(2)} sell + ${c.cycle_cost.toFixed(2)} cycle cost) — ${c.clears ? 'worth storing for later rather than selling it now.' : 'exporting it now would likely have been worth more.'}`,
  };
  let decisionRows = '';
  if (v.compare) {
    const c = v.compare;
    decisionRows += dotRow('shadow price', `${r.shadow_price.toFixed(2)} SEK/kWh`, 'var(--c-shadow)');
    decisionRows += dotRow(c.label, `${c.price.toFixed(2)} SEK/kWh`, null);
    decisionRows += `<div class="t-row" style="display:block; white-space:normal; margin-top:2px; color:var(--text-secondary)">${DECISION_SENTENCE[c.case](c)}</div>`;
  } else {
    decisionRows += `<div class="t-row" style="color:var(--text-muted)">no shadow price recorded this period</div>`;
  }

  decisionRows += `<div class="t-row" style="opacity:0.8; margin-top:6px"><span>total value (top candidate)</span><b>${v.total_value >= 0 ? '+' : ''}${v.total_value.toFixed(2)} SEK</b></div>`;
  decisionRows += dotRow('reward', `${v.reward >= 0 ? '+' : ''}${v.reward.toFixed(2)} SEK`, null) +
    // import_cost/export_revenue/battery_wear_cost are all non-negative
    // magnitudes by construction (a price × a kWh flow) -- plain subtraction.
    subRow(`${r.export_revenue.toFixed(2)} export revenue &minus; ${r.import_cost.toFixed(2)} import cost &minus; ${r.battery_wear_cost.toFixed(2)} battery wear`);
  decisionRows += dotRow('future value', `${r.future_value >= 0 ? '+' : ''}${r.future_value.toFixed(2)} SEK`, null) +
    subRow('best achievable outcome from the resulting battery level onward');

  // ---- Outcome: what actually resulted -- both a retrospective accounting ----
  // check (cost basis/breakeven, which never entered the decision above) and
  // the same two KPIs the real dashboard shows (Net Grid Cost, Net Savings;
  // core/bess/models.py's EconomicData.grid_cost and
  // backend/api_dataclasses.py's netSavings) rather than the DP's internal
  // immediate_value, which duplicates them and isn't surfaced anywhere in
  // the live app (see TODO.md, issue #353).
  let outcomeRows = '';
  if (v.breakeven !== null && (v.home_profit !== null || v.export_profit !== null)) {
    outcomeRows += `<div class="t-row" style="opacity:0.8"><span>breakeven this period</span><b>${v.breakeven.toFixed(2)} SEK/kWh</b></div>` +
      subRow(`${r.cost_basis.toFixed(2)} cost basis + ${CYCLE_COST.toFixed(2)} cycle cost`);
    if (v.home_profit !== null) outcomeRows += dotRow('serving home profit', `${v.home_profit >= 0 ? '+' : ''}${v.home_profit.toFixed(2)} SEK`, 'var(--c-load)') +
      subRow(`${r.batt_to_home.toFixed(2)} kWh &times; (${r.buy.toFixed(2)} buy &minus; ${v.breakeven.toFixed(2)} breakeven)`);
    if (v.export_profit !== null) outcomeRows += dotRow('exporting profit', `${v.export_profit >= 0 ? '+' : ''}${v.export_profit.toFixed(2)} SEK`, 'var(--c-export)') +
      subRow(`${r.batt_to_grid.toFixed(2)} kWh &times; (${r.sell.toFixed(2)} sell &minus; ${v.breakeven.toFixed(2)} breakeven)`);
    if (v.home_profit !== null && v.export_profit !== null) outcomeRows += dotRow('combined marginal margin', `${((v.home_profit || 0) + (v.export_profit || 0)) >= 0 ? '+' : ''}${((v.home_profit || 0) + (v.export_profit || 0)).toFixed(2)} SEK`, null);
  }
  outcomeRows += dotRow('net grid cost', `${r.grid_cost.toFixed(2)} SEK`, null) +
    subRow('import cost &minus; export revenue') +
    dotRow('net savings', `${v.net_savings >= 0 ? '+' : ''}${v.net_savings.toFixed(2)} SEK`, null) +
    subRow('grid-only baseline &minus; net grid cost');

  tooltip.innerHTML = `<div class="t-time">${r.time} &middot; <span style="color:${INTENT_COLOR[r.intent]}">${r.intent}</span></div>
    <div class="t-action" style="color:${actionColor}">${actionLine}</div>
    <div class="t-section">Decision</div>${decisionRows}
    <div class="t-section">Outcome</div>${outcomeRows}
    <div class="t-section">Price</div>${priceRows}
    <div class="t-section">Energy</div>${energyRows}
    <div class="t-section">Battery</div>${batteryRows}
    <div class="t-section">Source</div>
    <div class="t-row"><span>data</span><b>${r.source}</b></div>`;
}

capture.addEventListener('mousemove', (evt) => {
  const px = svgPoint(evt);
  let idx = Math.round((px - PAD.left) / plotW * (n - 1));
  idx = Math.max(0, Math.min(n - 1, idx));
  lastHoverIdx = idx;
  renderTooltip(idx);
});
capture.addEventListener('mouseleave', () => {
  lastHoverIdx = null;
  hoverLine.style.opacity = 0;
  Object.values(seriesDots).forEach(d => d.style.opacity = 0);
  dotSoe.style.opacity = 0; tooltip.style.opacity = 0;
});
</script>
