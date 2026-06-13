import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { emptyPerPlatformSensors, HUAWEI_SOLAR_DEFAULT_SENSORS, HUAWEI_SOLAR_DEFAULT_SHARED_SENSORS } from '../../lib/sensorDefinitions';
import { SensorConfigSection, type InverterForm } from './SensorConfigSection';

function renderSection(inverterForm: InverterForm = { inverterPlatform: 'growatt_server_min', deviceId: '' }) {
  const sensors = emptyPerPlatformSensors(inverterForm.inverterPlatform);
  const onChange = vi.fn();
  const onInverterChange = vi.fn();

  render(
    <SensorConfigSection
      sensors={sensors}
      onChange={onChange}
      inverterForm={inverterForm}
      onInverterChange={onInverterChange}
      discovery={null}
    />,
  );

  return { sensors, onChange, onInverterChange };
}

describe('SensorConfigSection inverter family selector', () => {
  it('renders Huawei Solar as an equal top-level inverter family', () => {
    renderSection();

    const tabs = screen.getAllByRole('tab');

    expect(tabs).toHaveLength(3);
    expect(screen.getByRole('tab', { name: 'Growatt Cloud' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'SolaX Modbus' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Huawei Solar' })).toBeInTheDocument();
  });

  it('shows only Huawei Solar variant content when Huawei family is active', () => {
    renderSection({ inverterPlatform: 'huawei_solar', deviceId: '' });

    expect(screen.getByRole('tab', { name: 'Huawei Solar' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: 'Huawei Solar — Experimental read-only' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Growatt MIN/GEN4' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'SolaX Native' })).not.toBeInTheDocument();
    expect(screen.getByText(/Active battery control is not implemented/)).toBeInTheDocument();
  });

  it('selects Huawei Solar without changing its platform id', async () => {
    const user = userEvent.setup();
    const { onChange, onInverterChange, sensors } = renderSection();

    await user.click(screen.getByRole('tab', { name: 'Huawei Solar' }));

    expect(onInverterChange).toHaveBeenCalledWith({ inverterPlatform: 'huawei_solar', deviceId: '' });
    expect(onChange).toHaveBeenCalledWith({
      ...sensors,
      platform: 'huawei_solar',
      huawei_solar: HUAWEI_SOLAR_DEFAULT_SENSORS,
      shared: HUAWEI_SOLAR_DEFAULT_SHARED_SENSORS,
    });
  });
});
