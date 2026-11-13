import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import { clearForceMode, getForceMode, setForceMode } from '../api/scheduleApi';
import { ForceModeState } from '../types';

const POLL_MS = 60_000;

interface ForceModeContextValue {
  // null until the first fetch succeeds (e.g. while the backend is starting).
  state: ForceModeState | null;
  // Both reject on failure so the caller can show its own message.
  setMode: (mode: string) => Promise<void>;
  clear: () => Promise<void>;
}

const ForceModeContext = createContext<ForceModeContextValue | null>(null);

// The one copy of force-mode state for the banner, the control and the status
// card. The poll also picks up a change made elsewhere (another tab, an HA
// automation) and retries a fetch that failed while the backend was starting.
export function ForceModeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ForceModeState | null>(null);

  const refresh = useCallback(() => {
    getForceMode()
      .then(setState)
      .catch((err) => console.error('Failed to load force mode:', err));
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  const setMode = useCallback(async (mode: string) => {
    setState(await setForceMode(mode));
  }, []);

  const clear = useCallback(async () => {
    setState(await clearForceMode());
  }, []);

  return (
    <ForceModeContext.Provider value={{ state, setMode, clear }}>
      {children}
    </ForceModeContext.Provider>
  );
}

export function useForceMode(): ForceModeContextValue {
  const ctx = useContext(ForceModeContext);
  if (!ctx) {
    throw new Error('useForceMode must be used within ForceModeProvider');
  }
  return ctx;
}
