import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSettings } from '../useSettings'

vi.mock('../../lib/api', () => ({
  default: {
    get: vi.fn(),
  },
}))

import api from '../../lib/api'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useSettings', () => {
  it('fetches settings on mount', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        battery: { capacity: 10, minSoc: 10, maxSoc: 90 },
        electricityPrice: { provider: 'nordpool', currency: 'SEK' },
      },
    })

    const { result } = renderHook(() => useSettings())

    expect(result.current.isLoading).toBe(true)

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockGet).toHaveBeenCalledWith('/api/settings')
    expect(result.current.batterySettings).toEqual({
      capacity: 10,
      minSoc: 10,
      maxSoc: 90,
    })
    expect(result.current.electricitySettings).toEqual({
      provider: 'nordpool',
      currency: 'SEK',
    })
    expect(result.current.error).toBeNull()
  })

  it('handles missing battery settings', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        electricityPrice: { provider: 'octopus' },
      },
    })

    const { result } = renderHook(() => useSettings())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.batterySettings).toBeNull()
    expect(result.current.electricitySettings).toEqual({ provider: 'octopus' })
  })

  it('sets error on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('Network error'))

    const { result } = renderHook(() => useSettings())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.error).toBe('Network error')
    expect(result.current.batterySettings).toBeNull()
  })
})
