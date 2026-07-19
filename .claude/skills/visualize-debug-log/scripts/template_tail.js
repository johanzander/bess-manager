
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
  { key: 'sell', label: 'Sell price', color: 'var(--sell-line)', get: r => r.sell, panel: 'price', defaultOn: true },
  { key: 'buy', label: 'Buy price', color: 'var(--buy-line)', get: r => r.buy, panel: 'price', defaultOn: true, dashed: true },
  { key: 'shadow', label: 'Shadow price', color: 'var(--c-shadow)', get: r => r.shadow_price, panel: 'price', defaultOn: false, gapped: true },
  { key: 'costbasis', label: 'Cost basis (stored energy)', color: 'var(--c-solar-flow)', get: r => r.cost_basis, panel: 'price', defaultOn: false, gapped: true },
  { key: 'breakeven', label: 'Breakeven (cost basis + cycle cost)', color: 'var(--c-solar-store)', get: r => r.cost_basis > 0 ? r.cost_basis + CYCLE_COST : 0, panel: 'price', defaultOn: false, gapped: true, dashed: true },
];
// Energy Trend series — Growatt-app style: six independently toggleable overlaid series.
const ENERGY_SERIES = [
  { key: 'export', label: 'Exported to Grid', color: 'var(--s-export)', get: r => r.solar_to_grid + r.batt_to_grid, panel: 'energy', defaultOn: true },
  { key: 'pv', label: 'Photovoltaic Output', color: 'var(--s-pv)', get: r => r.solar, panel: 'energy', defaultOn: true },
  { key: 'dis', label: 'Discharging', color: 'var(--s-dis)', get: r => r.batt_to_home + r.batt_to_grid, panel: 'energy', defaultOn: true },
  { key: 'imp', label: 'Imported From Grid', color: 'var(--s-imp)', get: r => r.grid_to_home + r.grid_to_batt, panel: 'energy', defaultOn: true },
  { key: 'chg', label: 'Charging', color: 'var(--s-chg)', get: r => r.solar_to_batt + r.grid_to_batt, panel: 'energy', defaultOn: true },
  { key: 'load', label: 'Load Consumption', color: 'var(--s-load)', get: r => r.load, panel: 'energy', defaultOn: true },
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
  return `<button type="button" class="swatch${off}" data-key="${s.key}"><span class="dot" style="background:${s.color}"></span>${s.label}</button>`;
}
const priceButtons = PRICE_SERIES.map(seriesButton).join('');
const energyButtons = ENERGY_SERIES.map(seriesButton).join('');
const intentSwatches = INTENT_ORDER.map(k =>
  `<span class="swatch"><span class="dot" style="background:${INTENT_COLOR[k]}"></span>${k}</span>`
).join('');
legend.innerHTML = `${priceButtons}` +
  `<span class="swatch" style="opacity:0.7">|</span>${energyButtons}` +
  `<span class="swatch" style="opacity:0.7">|</span>${intentSwatches}` +
  `<span class="swatch" style="opacity:0.75">(background tint = optimizer intent)</span>`;

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

  const chargeTotal = r.solar_to_batt + r.grid_to_batt;
  const dischargeTotal = r.batt_to_home + r.batt_to_grid;
  let actionLine, actionColor;
  if (chargeTotal > 0) {
    const parts = [];
    if (r.solar_to_batt > 0) parts.push(`${r.solar_to_batt.toFixed(2)} solar`);
    if (r.grid_to_batt > 0) parts.push(`${r.grid_to_batt.toFixed(2)} grid`);
    actionLine = `⚡ +${chargeTotal.toFixed(2)} kWh charge (${parts.join(' + ')})`;
    actionColor = 'var(--s-chg)';
  } else if (dischargeTotal > 0) {
    const parts = [];
    if (r.batt_to_home > 0) parts.push(`${r.batt_to_home.toFixed(2)} home`);
    if (r.batt_to_grid > 0) parts.push(`${r.batt_to_grid.toFixed(2)} grid`);
    actionLine = `⚡ −${dischargeTotal.toFixed(2)} kWh discharge (${parts.join(' + ')})`;
    actionColor = 'var(--s-dis)';
  } else {
    actionLine = 'no battery action';
    actionColor = 'var(--text-muted)';
  }

  const showDpReasoning = activeSeries.has('shadow') || activeSeries.has('costbasis') || activeSeries.has('breakeven');

  let priceRows = `<div class="t-row"><span>sell</span><b>${r.sell.toFixed(2)} SEK/kWh</b></div>
    <div class="t-row"><span>buy</span><b>${r.buy.toFixed(2)} SEK/kWh</b></div>`;
  if (activeSeries.has('shadow') && r.shadow_price > 0) priceRows += `<div class="t-row"><span>shadow price</span><b>${r.shadow_price.toFixed(2)} SEK/kWh</b></div>`;
  if (activeSeries.has('costbasis') && r.cost_basis > 0) priceRows += `<div class="t-row"><span>cost basis (stored energy)</span><b>${r.cost_basis.toFixed(2)} SEK/kWh</b></div>`;
  if (activeSeries.has('breakeven') && r.cost_basis > 0) priceRows += `<div class="t-row"><span>breakeven (this period)</span><b>${(r.cost_basis + CYCLE_COST).toFixed(2)} SEK/kWh</b></div>`;

  const energyRows = `<div class="t-row"><span>PV output</span><b>${r.solar.toFixed(2)} kWh</b></div>
    <div class="t-row"><span>load</span><b>${r.load.toFixed(2)} kWh</b></div>
    <div class="t-row"><span>exported to grid</span><b>${(r.solar_to_grid + r.batt_to_grid).toFixed(2)} kWh</b></div>
    <div class="t-row"><span>imported from grid</span><b>${(r.grid_to_home + r.grid_to_batt).toFixed(2)} kWh</b></div>`;

  const batteryRows = `<div class="t-row"><span>SOE</span><b>${r.soe_start.toFixed(2)} &rarr; ${r.soe_end.toFixed(2)} kWh</b></div>
    <div class="t-row"><span>SOE &Delta;</span><b>${(r.soe_end - r.soe_start >= 0 ? '+' : '')}${(r.soe_end - r.soe_start).toFixed(2)} kWh</b></div>`;

  let dpRows = '';
  if (showDpReasoning && r.immediate_value !== 0) dpRows += `<div class="t-row"><span>immediate value</span><b>${r.immediate_value.toFixed(2)} SEK</b></div>`;
  if (showDpReasoning && r.future_value !== 0) dpRows += `<div class="t-row"><span>future value</span><b>${r.future_value.toFixed(2)} SEK</b></div>`;
  if (showDpReasoning && r.economic_chain) dpRows += `<div class="t-row" style="display:block; white-space:normal; margin-top:2px; color:var(--text-secondary)">${r.economic_chain}</div>`;
  if (showDpReasoning && !dpRows) dpRows = `<div class="t-row" style="color:var(--text-muted)">no DP decision recorded this period</div>`;

  tooltip.innerHTML = `<div class="t-time">${r.time} &middot; <span style="color:${INTENT_COLOR[r.intent]}">${r.intent}</span></div>
    <div class="t-action" style="color:${actionColor}">${actionLine}</div>
    <div class="t-section">Price</div>${priceRows}
    <div class="t-section">Energy</div>${energyRows}
    <div class="t-section">Battery</div>${batteryRows}
    ${showDpReasoning ? `<div class="t-section">DP reasoning</div>${dpRows}` : ''}
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
