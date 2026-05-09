// Helpers for the "Report a Problem" flow:
// 1. download the debug bundle locally so the user can attach it to the issue
// 2. build a pre-filled GitHub issue URL the user can review and submit

import api from './api';

const REPO_URL = 'https://github.com/johanzander/bess-manager';

export interface IssueDraft {
  title?: string;
  description?: string;
}

/**
 * Trigger a download of the debug bundle. Returns the suggested filename so
 * callers can show it to the user (helping them find it for drag-drop into
 * the GitHub issue editor).
 */
export async function downloadDebugBundle(): Promise<string> {
  const response = await api.get('/api/export-debug-data', { responseType: 'blob' });
  const contentDisposition = response.headers['content-disposition'] as string | undefined;
  let filename = 'bess-debug.md';
  if (contentDisposition) {
    const m = contentDisposition.match(/filename=(.+)/);
    if (m) filename = m[1].replace(/"/g, '');
  }
  const blob = new Blob([response.data], { type: 'text/markdown' });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
  return filename;
}

/**
 * Build a GitHub "new issue" URL with title, body, and labels pre-filled.
 * The body includes a placeholder reminding the user to drag-drop the
 * debug file (which we just downloaded) into the issue editor.
 *
 * GitHub's URL length limit is ~8 KB; we keep the body short on purpose.
 */
export function buildIssueUrl(
  draft: IssueDraft,
  filename: string,
): string {
  const title = draft.title?.trim() || 'Bug report';
  const description = draft.description?.trim() || '_(no description provided)_';
  const body = [
    '## What happened',
    description,
    '',
    '## Debug bundle',
    `Please drag-and-drop **${filename}** from your Downloads folder into the editor below before submitting.`,
    'The file contains your version, settings, recent logs, and the raw HA discovery dump that the maintainers need to reproduce the issue.',
    '',
    '<!-- drag the debug file here -->',
  ].join('\n');

  const params = new URLSearchParams({
    title,
    body,
    labels: 'bug,needs-debug-log',
  });
  return `${REPO_URL}/issues/new?${params.toString()}`;
}

/**
 * One-call helper that runs the whole flow:
 * - downloads the debug bundle (user gets the file in their Downloads folder)
 * - opens a pre-filled GitHub issue in a new tab
 *
 * Returns the filename so the UI can show "Saved as <filename>".
 * Throws on download failure so the caller can surface an error.
 */
export async function reportProblem(draft: IssueDraft): Promise<string> {
  const filename = await downloadDebugBundle();
  const url = buildIssueUrl(draft, filename);
  window.open(url, '_blank', 'noopener,noreferrer');
  return filename;
}
