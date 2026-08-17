import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useRouteLocale } from './useRouteLocale';
import { makeRouterQueryWrapper } from '../test/utils';

function makeWrapper(initialPath: string, pattern: string) {
  return makeRouterQueryWrapper({ initialPath, routePatterns: [pattern] }).wrapper;
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
