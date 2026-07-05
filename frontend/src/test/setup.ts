import '@testing-library/jest-dom'

// Node 26 ships an experimental global `localStorage` that is `undefined`
// unless --localstorage-file is provided, shadowing jsdom's implementation.
// Install a minimal in-memory mock so storage-dependent tests work.
if (typeof localStorage === 'undefined') {
  const store: Record<string, string> = {}
  const mock = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value) },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { Object.keys(store).forEach(k => delete store[k]) },
    get length() { return Object.keys(store).length },
    key: (i: number) => Object.keys(store)[i] ?? null,
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: mock,
    writable: true,
    configurable: true,
  })
}

// jsdom has no layout engine, so recharts' ResponsiveContainer (which relies
// on ResizeObserver to measure its parent) needs a stub to mount at all.
if (typeof ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}
