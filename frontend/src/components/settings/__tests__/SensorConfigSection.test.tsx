import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { emptyPerPlatformSensors } from '../../../lib/sensorDefinitions';
import { SensorConfigSection, type DiscoveryResult } from '../SensorConfigSection';

const noInverterDetected: DiscoveryResult = {
  growattFound: false,
  growattDeviceId: null,
  solaxFound: false,
  solaxHasGrowattTou: false,
  solaxHasGrowattGen3: false,
  solisFound: false,
  huaweiFound: false,
  huaweiDeviceId: null,
  nordpoolFound: false,
  nordpoolArea: null,
  nordpoolCustomArea: null,
  nordpoolCustomEntity: null,
  nordpoolConfigEntryId: null,
  octopusFound: false,
  entsoeFound: false,
  entsoeEntity: null,
  sensors: {},
  missingSensors: [],
  detectedPhaseCount: null,
  currency: null,
  vatMultiplier: null,
};

describe('SensorConfigSection', () => {
  it('allows manual Huawei selection when auto-detection finds no Huawei integration', async () => {
    const user = userEvent.setup();
    const onInverterChange = vi.fn();

    render(
      <SensorConfigSection
        sensors={emptyPerPlatformSensors('growatt_server_min')}
        onChange={vi.fn()}
        inverterForm={{
          inverterPlatform: 'growatt_server_min',
          deviceId: '',
          serviceDomain: '',
        }}
        onInverterChange={onInverterChange}
        discovery={noInverterDetected}
      />,
    );

    const huaweiTab = screen.getByRole('tab', { name: /Huawei/i });
    expect(huaweiTab).toBeEnabled();

    await user.click(huaweiTab);

    expect(onInverterChange).toHaveBeenCalledWith(
      expect.objectContaining({ inverterPlatform: 'huawei_solar_luna2000' }),
    );
  });
});
