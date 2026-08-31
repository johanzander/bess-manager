import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import DeprecationBanner from '../DeprecationBanner';

const DISMISS_KEY = 'bess.influxdbDeprecationDismissed';

describe('DeprecationBanner', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders nothing when show is false', () => {
    const { container } = render(<DeprecationBanner show={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the InfluxDB deprecation notice when show is true', () => {
    render(<DeprecationBanner show={true} />);
    expect(screen.getByText(/InfluxDB support is going away/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Migration notes/i })).toHaveAttribute(
      'href',
      expect.stringContaining('#migrating-from-the-influxdb-add-on'),
    );
  });

  it('dismissing hides it and persists across remounts', () => {
    const { unmount } = render(<DeprecationBanner show={true} />);
    fireEvent.click(screen.getByRole('button', { name: /Dismiss/i }));
    expect(screen.queryByText(/InfluxDB support is going away/i)).not.toBeInTheDocument();
    expect(localStorage.getItem(DISMISS_KEY)).toBe('1');

    unmount();
    render(<DeprecationBanner show={true} />);
    expect(screen.queryByText(/InfluxDB support is going away/i)).not.toBeInTheDocument();
  });

  it('stays hidden when already dismissed in localStorage', () => {
    localStorage.setItem(DISMISS_KEY, '1');
    const { container } = render(<DeprecationBanner show={true} />);
    expect(container).toBeEmptyDOMElement();
  });
});
