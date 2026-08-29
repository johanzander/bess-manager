import { describe, expect, it } from 'vitest';

import {
  INTEGRATIONS,
  VALID_PLATFORMS,
  SHARED_INTEGRATION_IDS,
  getActiveSensorsFlat,
  emptyPerPlatformSensors,
} from '../sensorDefinitions';

describe('SHARED_INTEGRATION_IDS', () => {
  // The registry is what routes an integration's sensors into `sensors.shared`,
  // which is the only non-platform dict the backend ever merges. An
  // integration that renders but is missing here silently swallows whatever
  // the user types: it writes to a top-level key nothing reads.
  it('contains every integration that is not an inverter platform', () => {
    const platformIds = new Set<string>(VALID_PLATFORMS);
    const nonPlatform = INTEGRATIONS.map((i) => i.id).filter((id) => !platformIds.has(id));

    const unregistered = nonPlatform.filter((id) => !SHARED_INTEGRATION_IDS.has(id));

    expect(unregistered).toEqual([]);
  });

  it('routes a shared integration sensor through to the flat backend payload', () => {
    const sensors = emptyPerPlatformSensors('huawei_solar_luna2000');
    sensors.shared = { consumption_overlay: 'sensor.bess_consumption_overlay' };

    expect(getActiveSensorsFlat(sensors)['consumption_overlay']).toBe(
      'sensor.bess_consumption_overlay',
    );
  });
});
