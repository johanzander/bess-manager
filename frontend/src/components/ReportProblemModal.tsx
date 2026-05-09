import { useEffect, useRef, useState } from 'react';
import { X, Download, ExternalLink, AlertCircle, CheckCircle } from 'lucide-react';
import { downloadDebugBundle, buildIssueUrl } from '../lib/reportProblem';

interface ReportProblemModalProps {
  open: boolean;
  onClose: () => void;
  initialTitle?: string;
  initialDescription?: string;
}

export default function ReportProblemModal({
  open,
  onClose,
  initialTitle = '',
  initialDescription = '',
}: ReportProblemModalProps) {
  const [title, setTitle] = useState(initialTitle);
  const [description, setDescription] = useState(initialDescription);
  const [activeAction, setActiveAction] = useState<'download' | 'issue' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ filename: string; issueFiled: boolean } | null>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Reset form whenever modal is opened with new defaults
  useEffect(() => {
    if (open) {
      setTitle(initialTitle);
      setDescription(initialDescription);
      setError(null);
      setResult(null);
      setActiveAction(null);
      setTimeout(() => titleInputRef.current?.focus(), 50);
    }
  }, [open, initialTitle, initialDescription]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const handleDownload = async () => {
    setActiveAction('download');
    setError(null);
    try {
      const filename = await downloadDebugBundle();
      setResult({ filename, issueFiled: false });
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Failed to generate debug bundle. Please check the logs.',
      );
    } finally {
      setActiveAction(null);
    }
  };

  const handleFileIssue = async () => {
    setActiveAction('issue');
    setError(null);
    try {
      const filename = await downloadDebugBundle();
      const url = buildIssueUrl({ title, description }, filename);
      window.open(url, '_blank', 'noopener,noreferrer');
      setResult({ filename, issueFiled: true });
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : 'Failed to generate debug bundle. Please check the logs.',
      );
    } finally {
      setActiveAction(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-problem-title"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2
            id="report-problem-title"
            className="text-lg font-semibold text-gray-900 dark:text-gray-100"
          >
            Report a Problem
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            Download a debug bundle and attach it to a GitHub issue so we can
            investigate. All personal data and credentials are automatically
            scrubbed.
          </p>

          <div className="space-y-1">
            <label
              htmlFor="report-title"
              className="block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              Title
            </label>
            <input
              id="report-title"
              ref={titleInputRef}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={!!activeAction || !!result}
              placeholder="Brief summary of what went wrong"
              className="w-full px-3 py-2 text-sm rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="report-description"
              className="block text-xs font-medium text-gray-700 dark:text-gray-300"
            >
              What happened?
            </label>
            <textarea
              id="report-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!!activeAction || !!result}
              rows={4}
              placeholder="Steps to reproduce, expected vs. actual behaviour, etc."
              className="w-full px-3 py-2 text-sm rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y disabled:opacity-60"
            />
          </div>

          {error && (
            <div className="flex gap-2 px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md text-sm text-red-800 dark:text-red-200">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="flex gap-2 px-3 py-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md text-sm text-green-800 dark:text-green-200">
              <CheckCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">Saved as {result.filename}</p>
                {result.issueFiled && (
                  <p className="text-xs mt-0.5 text-green-700 dark:text-green-300">
                    A GitHub issue draft opened in a new tab. Drag the file
                    from your Downloads folder into the editor before submitting.
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <>
              <button
                onClick={handleDownload}
                disabled={!!activeAction}
                className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Download className={`h-4 w-4${activeAction === 'download' ? ' animate-pulse' : ''}`} />
                {activeAction === 'download' ? 'Generating...' : 'Download Debug Data'}
              </button>
              <button
                onClick={handleFileIssue}
                disabled={!!activeAction}
                className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white"
              >
                <ExternalLink className={`h-4 w-4${activeAction === 'issue' ? ' animate-pulse' : ''}`} />
                {activeAction === 'issue' ? 'Generating...' : 'File GitHub Issue'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
