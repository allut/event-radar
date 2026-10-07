import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePathLocale } from './usePathLocale';
import { setLocale } from '../lib/auth';
import { makeRouterQueryWrapper } from '../test/utils';

describe('usePathLocale', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns the locale segment of a prefixed URL', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/ru/explore' });
    const { result } = renderHook(() => usePathLocale(), { wrapper });
    expect(result.current).toBe('ru');
  });

  it('returns Estonian on a bare URL', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/faq' });
    const { result } = renderHook(() => usePathLocale(), { wrapper });
    expect(result.current).toBe('et');
  });

  it('returns Estonian for an unrecognized locale segment', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/xx/explore' });
    const { result } = renderHook(() => usePathLocale(), { wrapper });
    expect(result.current).toBe('et');
  });

  it('ignores a saved preference that disagrees with the URL', () => {
    setLocale('en');
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/faq' });
    const { result } = renderHook(() => usePathLocale(), { wrapper });
    expect(result.current).toBe('et');
  });
});
