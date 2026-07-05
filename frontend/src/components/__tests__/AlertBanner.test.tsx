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

describe('AlertBanner active issues are not dismissible', () => {
  it('renders no dismiss button while a critical error is active', () => {
    renderBanner({ hasCriticalErrors: true, hasWarnings: false })

    expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument()
  })

  it('renders no dismiss button while a warning is active', () => {
    renderBanner({
      hasCriticalErrors: false,
      hasWarnings: true,
      criticalIssues: [{ component: 'Solar Forecast', description: 'sensor unavailable', status: 'WARNING' }],
    })

    expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument()
  })
})

describe('AlertBanner recovered state', () => {
  const recoveries = [
    { component: 'Battery SOC', previousStatus: 'ERROR', timestamp: '2026-07-05T14:32:00' },
  ]

  it('renders nothing when there are no active issues and no recoveries', () => {
    const { container } = renderBanner({ hasCriticalErrors: false, hasWarnings: false, criticalIssues: [], recoveries: [] })

    expect(container).toBeEmptyDOMElement()
  })

  it('renders a recovered banner when there are no active issues but a pending recovery exists', () => {
    renderBanner({ hasCriticalErrors: false, hasWarnings: false, criticalIssues: [], recoveries })

    expect(screen.getByText(/battery soc/i)).toBeInTheDocument()
  })

  it('calls onAcknowledgeRecoveries when the recovered banner is dismissed', () => {
    const onAcknowledgeRecoveries = vi.fn()
    renderBanner({
      hasCriticalErrors: false,
      hasWarnings: false,
      criticalIssues: [],
      recoveries,
      onAcknowledgeRecoveries,
    })

    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))

    expect(onAcknowledgeRecoveries).toHaveBeenCalledTimes(1)
  })

  it('active critical errors take priority over a pending recovery', () => {
    renderBanner({ hasCriticalErrors: true, hasWarnings: false, recoveries })

    expect(screen.getByText(/critical system issues detected/i)).toBeInTheDocument()
  })
})

describe('AlertBanner expandable issue list', () => {
  const manyIssues = Array.from({ length: 5 }, (_, i) => ({
    component: `Sensor ${i}`,
    description: 'sensor unavailable',
    status: 'ERROR',
  }))

  it('truncates to 3 issues with a "Show all" toggle when there are more than 3', () => {
    renderBanner({ criticalIssues: manyIssues, totalCriticalIssues: 5 })

    expect(screen.queryByText(/sensor 3/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show all/i })).toBeInTheDocument()
  })

  it('expands to show all issues when "Show all" is clicked', () => {
    renderBanner({ criticalIssues: manyIssues, totalCriticalIssues: 5 })

    fireEvent.click(screen.getByRole('button', { name: /show all/i }))

    expect(screen.getByText(/sensor 3/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show less/i })).toBeInTheDocument()
  })
})
