/** Pick a nice step size and generate evenly-spaced ticks for a Y-axis range. */
export function niceYAxis(
  min: number,
  max: number,
  targetTicks = 5,
): { yMin: number; yMax: number; ceiling: number; ticks: number[] } {
  const range = max - min || 0.1;
  const niceSteps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];
  const rawStep = range / (targetTicks - 1);
  const step = niceSteps.find(s => s >= rawStep) ?? Math.ceil(rawStep);
  const yMin = Math.floor(min / step) * step;
  const yMax = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = yMin; v <= yMax + step * 0.01; v += step) {
    ticks.push(Math.round(v * 1000) / 1000);
  }
  return { yMin, yMax, ceiling: yMax, ticks };
}
