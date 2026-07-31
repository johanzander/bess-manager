import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ReportProblemModal from '../ReportProblemModal';
import * as reportProblemLib from '../../lib/reportProblem';

describe('ReportProblemModal - File GitHub Issue', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('opens the tab synchronously (before the debug bundle download resolves) so browsers do not block the popup', async () => {
    let resolveDownload: (filename: string) => void = () => {};
    const downloadPromise = new Promise<string>((resolve) => {
      resolveDownload = resolve;
    });
    vi.spyOn(reportProblemLib, 'downloadDebugBundle').mockReturnValue(downloadPromise);
    vi.spyOn(reportProblemLib, 'buildIssueUrl').mockReturnValue(
      'https://github.com/johanzander/bess-manager/issues/new?title=x',
    );

    const fakeTab = { location: { href: '' }, opener: {} };
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(fakeTab as unknown as Window);

    render(<ReportProblemModal open={true} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /file github issue/i }));

    // Must happen synchronously, in the same tick as the click — not after
    // the download awaits — otherwise browsers treat it as an untrusted
    // popup and block it silently. Must NOT pass the 'noopener' feature:
    // browsers return null from window.open when it's set, which would
    // discard the handle needed to navigate the tab once the URL is ready.
    expect(openSpy).toHaveBeenCalledWith('', '_blank');
    expect(fakeTab.opener).toBeNull();
    expect(fakeTab.location.href).toBe('');

    resolveDownload('bess-debug.md');

    await waitFor(() =>
      expect(fakeTab.location.href).toBe(
        'https://github.com/johanzander/bess-manager/issues/new?title=x',
      ),
    );
  });
});
