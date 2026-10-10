import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFitsViewport } from './useFitsViewport';

function makeEl(height: number, top: string): HTMLElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'offsetHeight', { configurable: true, get: () => height });
  el.style.top = top;
  return el;
}

describe('useFitsViewport', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is false with no element', () => {
    const { result } = renderHook(() => useFitsViewport(null));
    expect(result.current).toBe(false);
  });

  it('is true when the element plus its sticky top offset fits the viewport', () => {
    vi.stubGlobal('innerHeight', 1000);
    const { result } = renderHook(() => useFitsViewport(makeEl(900, '96px')));
    expect(result.current).toBe(true);
  });

  it('is false when the element plus its top offset overflows the viewport', () => {
    vi.stubGlobal('innerHeight', 1000);
    const { result } = renderHook(() => useFitsViewport(makeEl(950, '96px')));
    expect(result.current).toBe(false);
  });

  it('re-measures on window resize', () => {
    vi.stubGlobal('innerHeight', 1000);
    const { result } = renderHook(() => useFitsViewport(makeEl(950, '96px')));
    expect(result.current).toBe(false);
    act(() => {
      vi.stubGlobal('innerHeight', 1200);
      window.dispatchEvent(new Event('resize'));
    });
    expect(result.current).toBe(true);
  });
});
