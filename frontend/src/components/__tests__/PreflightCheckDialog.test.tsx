import { render, screen, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import PreflightCheckDialog from '../PreflightCheckDialog'

vi.mock('../../lib/api', () => ({
  default: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}))

import api from '../../lib/api'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PreflightCheckDialog', () => {
  it('enables the button when all required checks pass and optional component is NOT_CONFIGURED', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Historical Data Access', status: 'NOT_CONFIGURED', required: false },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      const button = screen.getByRole('button', { name: /enable live control/i })
      expect(button).not.toBeDisabled()
    })
  })

  it('enables the button when an optional component has WARNING status', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Power Monitoring', status: 'WARNING', required: false },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      const button = screen.getByRole('button', { name: /enable live control/i })
      expect(button).not.toBeDisabled()
    })
  })

  it('enables the button when a required component has WARNING status', async () => {
    // #558: "Energy Prediction" is required under the sensor consumption
    // strategy, but its solar-forecast member stays optional. A required
    // component only reports WARNING when every required method works, so a
    // failing optional member must not block leaving demo mode.
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Energy Prediction', status: 'WARNING', required: true },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      const button = screen.getByRole('button', { name: /enable live control/i })
      expect(button).not.toBeDisabled()
    })
  })

  it('disables the button when a required component has ERROR status', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'ERROR', required: true },
          { name: 'Historical Data Access', status: 'NOT_CONFIGURED', required: false },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      const button = screen.getByRole('button', { name: /enable live control/i })
      expect(button).toBeDisabled()
    })
  })

  it('shows "Some checks failed" banner when a required component has ERROR status', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'ERROR', required: true },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/some checks failed/i)).toBeInTheDocument()
    })
  })

  it('does not show an optional component in ERROR as passing', async () => {
    // check_historical_data_access() reports required:false with status ERROR
    // when InfluxDB is configured but unreachable/misconfigured.
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Historical Data Access', status: 'ERROR', required: false },
        ],
      },
    })

    const { container } = render(
      <PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />
    )

    await waitFor(() => {
      expect(screen.getByText('Historical Data Access')).toBeInTheDocument()
    })

    // Exactly one green check (Battery Control) — the failing optional
    // component must not be one of them.
    expect(container.querySelectorAll('.text-green-500')).toHaveLength(1)
    expect(container.querySelectorAll('.text-amber-500')).toHaveLength(1)
  })

  it('still enables the button when only an optional component has ERROR status', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Historical Data Access', status: 'ERROR', required: false },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      const button = screen.getByRole('button', { name: /enable live control/i })
      expect(button).not.toBeDisabled()
    })
    expect(screen.getByText(/some optional components reported problems/i)).toBeInTheDocument()
  })

  it('shows success banner when all required checks pass', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        checks: [
          { name: 'Battery Control', status: 'OK', required: true },
          { name: 'Historical Data Access', status: 'NOT_CONFIGURED', required: false },
        ],
      },
    })

    render(<PreflightCheckDialog open={true} onClose={() => {}} onConfirm={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText(/all checks passed/i)).toBeInTheDocument()
    })
  })
})
