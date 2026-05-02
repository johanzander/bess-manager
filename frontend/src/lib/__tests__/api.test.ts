import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock window.location before importing api module
const mockPathname = vi.fn(() => '/')

beforeEach(() => {
  vi.resetModules()
  mockPathname.mockReturnValue('/')
})

describe('getBaseUrl', () => {
  it('returns empty string for non-ingress paths', async () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/' },
      writable: true,
    })

    const { default: api } = await import('../api')
    expect(api.defaults.baseURL).toBe('')
  })

  it('detects Home Assistant ingress path', async () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/api/hassio_ingress/abc123def/settings' },
      writable: true,
    })

    const { default: api } = await import('../api')
    expect(api.defaults.baseURL).toBe('/api/hassio_ingress/abc123def')
  })

  it('handles ingress root path', async () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/api/hassio_ingress/token456/' },
      writable: true,
    })

    const { default: api } = await import('../api')
    expect(api.defaults.baseURL).toBe('/api/hassio_ingress/token456')
  })
})
