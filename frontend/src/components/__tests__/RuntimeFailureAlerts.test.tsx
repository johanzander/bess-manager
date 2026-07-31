import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RuntimeFailureAlerts } from '../RuntimeFailureAlerts';
import { ReportProblemProvider } from '../ReportProblemContext';

const renderAlerts = (failures: Parameters<typeof RuntimeFailureAlerts>[0]['failures']) =>
  render(
    <ReportProblemProvider>
      <RuntimeFailureAlerts failures={failures} onDismiss={vi.fn()} onDismissAll={vi.fn()} />
    </ReportProblemProvider>,
  );

describe('RuntimeFailureAlerts', () => {
  it('renders the actual error message returned by the API', () => {
    renderAlerts([
      {
        id: '1',
        timestamp: '2026-07-31T07:53:04',
        operation: "Check sensor info for 'get_battery_soc'",
        category: 'sensor_read',
        error_message:
          "502 Server Error: Bad Gateway for url: http://supervisor/core/api/states/sensor.egm2h4l0g0_state_of_charge",
        occurrence_count: 1,
      },
    ]);

    expect(
      screen.getByText(/502 Server Error: Bad Gateway/),
    ).toBeInTheDocument();
  });
});
