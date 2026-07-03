import type { ComponentProps } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AlertBanner from '../AlertBanner'
import { ReportProblemProvider } from '../ReportProblemContext'

const renderBanner = (props: Partial<ComponentProps<typeof AlertBanner>> = {}) =>
  render(
    <MemoryRouter>
      <ReportProblemProvider>
        <AlertBanner
          hasCriticalErrors={true}
          hasWarnings={false}
          criticalIssues={[{ component: 'Battery SOC', description: 'sensor unavailable', status: 'ERROR' }]}
          totalCriticalIssues={1}
          {...props}
        />
      </ReportProblemProvider>
    </MemoryRouter>
  )

describe('AlertBanner recheck action', () => {
  it('calls onRecheck when the Recheck now button is clicked', () => {
    const onRecheck = vi.fn()
    renderBanner({ onRecheck })

    fireEvent.click(screen.getByRole('button', { name: /recheck now/i }))

    expect(onRecheck).toHaveBeenCalledTimes(1)
  })

  it('does not render a recheck button when onRecheck is not provided', () => {
    renderBanner()

    expect(screen.queryByRole('button', { name: /recheck now/i })).not.toBeInTheDocument()
  })

  it('disables the recheck button while isRechecking is true', () => {
    const onRecheck = vi.fn()
    renderBanner({ onRecheck, isRechecking: true })

    expect(screen.getByRole('button', { name: /rechecking/i })).toBeDisabled()
  })
})
