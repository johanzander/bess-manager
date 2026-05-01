import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useUserPreferences } from '../useUserPreferences'

beforeEach(() => {
  localStorage.clear()
})

describe('useUserPreferences', () => {
  it('returns default preferences when localStorage is empty', () => {
    const { result } = renderHook(() => useUserPreferences())

    expect(result.current.dataResolution).toBe('quarter-hourly')
  })

  it('reads stored preferences from localStorage', () => {
    localStorage.setItem(
      'bess_user_preferences',
      JSON.stringify({ dataResolution: 'hourly' })
    )

    const { result } = renderHook(() => useUserPreferences())

    expect(result.current.dataResolution).toBe('hourly')
  })

  it('falls back to defaults on invalid JSON', () => {
    localStorage.setItem('bess_user_preferences', 'not-json')

    const { result } = renderHook(() => useUserPreferences())

    expect(result.current.dataResolution).toBe('quarter-hourly')
  })

  it('setDataResolution updates state and localStorage', () => {
    const { result } = renderHook(() => useUserPreferences())

    act(() => {
      result.current.setDataResolution('hourly')
    })

    expect(result.current.dataResolution).toBe('hourly')
    expect(JSON.parse(localStorage.getItem('bess_user_preferences')!)).toEqual({
      dataResolution: 'hourly',
    })
  })

  it('setPreferences merges partial updates', () => {
    const { result } = renderHook(() => useUserPreferences())

    act(() => {
      result.current.setPreferences({ dataResolution: 'hourly' })
    })

    expect(result.current.preferences).toEqual({ dataResolution: 'hourly' })
  })
})
