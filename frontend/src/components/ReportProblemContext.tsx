import { createContext, useCallback, useContext, useState, ReactNode } from 'react';
import ReportProblemModal from './ReportProblemModal';

interface ReportProblemContextValue {
  // Open the modal, optionally pre-filling title/description (e.g. from
  // an inline "Report this" button on a runtime failure alert).
  openReportProblem: (defaults?: { title?: string; description?: string }) => void;
}

const ReportProblemContext = createContext<ReportProblemContextValue | null>(null);

export function ReportProblemProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [defaults, setDefaults] = useState<{ title?: string; description?: string }>({});

  const openReportProblem = useCallback(
    (d?: { title?: string; description?: string }) => {
      setDefaults(d ?? {});
      setOpen(true);
    },
    [],
  );

  return (
    <ReportProblemContext.Provider value={{ openReportProblem }}>
      {children}
      <ReportProblemModal
        open={open}
        onClose={() => setOpen(false)}
        initialTitle={defaults.title}
        initialDescription={defaults.description}
      />
    </ReportProblemContext.Provider>
  );
}

export function useReportProblem(): ReportProblemContextValue {
  const ctx = useContext(ReportProblemContext);
  if (!ctx) {
    throw new Error('useReportProblem must be used within ReportProblemProvider');
  }
  return ctx;
}
