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
