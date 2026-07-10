// Single source of truth for reading a period's battery strategic intent.
// The backend computes both fields (core/bess/decision_intelligence.py):
// strategicIntent is the DP-planned intent (defaults to "IDLE" when no plan
// covered the period), observedIntent is derived from real sensor flows and
// is only set for actual/historical periods. Every UI surface that displays
// or reasons about "what did the battery do this period" must resolve the
// two the same way, or displays can disagree about the same period.

export type StrategicIntent =
  | 'GRID_CHARGING'
  | 'SOLAR_STORAGE'
  | 'LOAD_SUPPORT'
  | 'BATTERY_EXPORT'
  | 'SOLAR_EXPORT'
  | 'IDLE';

export interface IntentSource {
  dataSource?: string;
  strategicIntent?: string;
  observedIntent?: string;
}

export function getIntent(hour: IntentSource): StrategicIntent {
  const raw =
    hour.dataSource === 'actual' && hour.observedIntent
      ? hour.observedIntent
      : hour.strategicIntent;
  return (raw as StrategicIntent) || 'IDLE';
}
