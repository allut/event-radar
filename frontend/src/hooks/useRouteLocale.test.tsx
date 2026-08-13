import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useRouteLocale } from './useRouteLocale';

function makeWrapper(initialPath: string, pattern: string) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path={pattern} element={<>{children}</>} />
        </Routes>
      </MemoryRouter>
    );
  }
  return Wrapper;
}

describe('useRouteLocale', () => {
  it('resolves a valid explicit segment', () => {
    const { result } = renderHook(() => useRouteLocale(), {
      wrapper: makeWrapper('/ru/settings', '/:locale/settings'),
    });
    expect(result.current).toBe('ru');
  });

  it('falls back to Estonian when no segment is matched', () => {
    const { result } = renderHook(() => useRouteLocale(), {
      wrapper: makeWrapper('/settings', '/settings'),
    });
    expect(result.current).toBe('et');
  });

  it('falls back to Estonian for an unrecognized segment', () => {
    const { result } = renderHook(() => useRouteLocale(), {
      wrapper: makeWrapper('/xx/settings', '/:locale/settings'),
    });
    expect(result.current).toBe('et');
  });
});
