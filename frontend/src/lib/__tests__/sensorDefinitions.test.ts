import { describe, expect, it } from 'vitest';

import {
  INTEGRATIONS,
  VALID_PLATFORMS,
  SHARED_INTEGRATION_IDS,
  getActiveSensorsFlat,
  emptyPerPlatformSensors,
} from '../sensorDefinitions';

describe('lifetime_load_consumption field availability', () => {
  // The HA Statistics consumption strategy (HomeFormSection) is enabled only
  // when a `lifetime_load_consumption` sensor is configured. A platform whose
  // wizard definition omits the field can never enable that strategy — even
  // when the user has a whole-home energy meter in HA (#730). Huawei/EMMA and
  // Solis both expose a real lifetime consumption entity, so both must offer
  // the field.
  it.each(['huawei_solar_luna2000', 'solis_modbus'])(
    '%s exposes an optional lifetime_load_consumption field',
    (platformId) => {
      const platform = INTEGRATIONS.find((i) => i.id === platformId);
      const field = platform?.sensorGroups
        .flatMap((g) => g.sensors)
        .find((s) => s.key === 'lifetime_load_consumption');

      expect(field).toBeDefined();
      expect(field?.required).toBe(false);
    },
  );
});

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
