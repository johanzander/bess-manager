import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useDashboardData } from '../useDashboardData'

vi.mock('../../api/scheduleApi', () => ({
  fetchDashboardData: vi.fn(),
}))

import { fetchDashboardData } from '../../api/scheduleApi'

const mockFetch = vi.mocked(fetchDashboardData)

beforeEach(() => {
  vi.clearAllMocks()
})

const fakeDashboard = {
  summary: { totalSavings: 12.5 },
  periods: [{ hour: 0, period: 0 }],
}

describe('useDashboardData', () => {
  it('fetches data on mount with default resolution', async () => {
    mockFetch.mockResolvedValueOnce(fakeDashboard)

    const { result } = renderHook(() => useDashboardData())

    expect(result.current.loading).toBe(true)

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(mockFetch).toHaveBeenCalledWith(undefined, 'quarter-hourly')
    expect(result.current.data).toEqual(fakeDashboard)
    expect(result.current.error).toBeNull()
  })

  it('passes date and resolution params', async () => {
    mockFetch.mockResolvedValueOnce(fakeDashboard)

    const { result } = renderHook(() => useDashboardData('2026-05-01', 'hourly'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(mockFetch).toHaveBeenCalledWith('2026-05-01', 'hourly')
  })

  it('sets error on fetch failure', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Server down'))

    const { result } = renderHook(() => useDashboardData())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Server down')
    expect(result.current.data).toBeNull()
  })

  it('refetch triggers a new fetch', async () => {
    mockFetch.mockResolvedValueOnce(fakeDashboard)

    const { result } = renderHook(() => useDashboardData())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    mockFetch.mockResolvedValueOnce({ ...fakeDashboard, summary: { totalSavings: 20 } })

    act(() => {
      result.current.refetch()
    })

    await waitFor(() => {
      expect(result.current.data?.summary?.totalSavings).toBe(20)
    })

    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})
