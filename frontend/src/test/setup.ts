import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi, beforeAll } from 'vitest';

// jsdom 29 + vitest 4 passes an invalid --localstorage-file which breaks localStorage.
// Replace it with an in-memory mock that clears between tests.
let _store: Record<string, string> = {};
const localStorageMock: Storage = {
  getItem: (key: string) => _store[key] ?? null,
  setItem: (key: string, value: string) => { _store[key] = String(value); },
  removeItem: (key: string) => { delete _store[key]; },
  clear: () => { _store = {}; },
  get length() { return Object.keys(_store).length; },
  key: (index: number) => Object.keys(_store)[index] ?? null,
};

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  localStorageMock.clear();
  vi.clearAllMocks();
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

Object.defineProperty(window, 'scrollTo', {
  writable: true,
  value: vi.fn(),
});
