import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useLocalePath } from './useLocalePath';
import { makeRouterQueryWrapper } from '../test/utils';

describe('useLocalePath', () => {
  it('prefixes a target with the locale segment of a prefixed URL', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/ru/explore' });
    const { result } = renderHook(() => useLocalePath(), { wrapper });
    expect(result.current('/settings')).toBe('/ru/settings');
  });

  it('leaves a target bare on a bare (Estonian) URL', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/explore' });
    const { result } = renderHook(() => useLocalePath(), { wrapper });
    expect(result.current('/settings')).toBe('/settings');
  });

  it('falls back to Estonian (bare) for an unrecognized locale segment', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/xx/explore' });
    const { result } = renderHook(() => useLocalePath(), { wrapper });
    expect(result.current('/settings')).toBe('/settings');
  });

  it('works when rendered outside <Routes> (no routePatterns, e.g. Footer mounted in App.tsx outside the route tree)', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/ru/contact' });
    const { result } = renderHook(() => useLocalePath(), { wrapper });
    expect(result.current('/privacy')).toBe('/ru/privacy');
  });

  it('preserves query string and hash on the target', () => {
    const { wrapper } = makeRouterQueryWrapper({ initialPath: '/ru/explore' });
    const { result } = renderHook(() => useLocalePath(), { wrapper });
    expect(result.current('/explore?category=music#top')).toBe('/ru/explore?category=music#top');
  });
});
