import { AlertCircle } from 'lucide-react';
import { useReportProblem } from './ReportProblemContext';

export default function ReportProblemButton() {
  const { openReportProblem } = useReportProblem();
  return (
    <button
      onClick={() => openReportProblem()}
      className="p-2 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
      title="Report a problem — generates a debug bundle and opens a GitHub issue"
      aria-label="Report a problem"
    >
      <AlertCircle className="h-5 w-5 text-gray-600 dark:text-gray-300" />
    </button>
  );
}
