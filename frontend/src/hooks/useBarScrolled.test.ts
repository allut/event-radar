import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useBarScrolled } from './useBarScrolled';

function scrollTo(y: number) {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
  act(() => {
    window.dispatchEvent(new Event('scroll'));
  });
}

afterEach(() => scrollTo(0));

describe('useBarScrolled', () => {
  it('starts unscrolled (so prerendered HTML is the unscrolled bar)', () => {
    expect(renderHook(() => useBarScrolled()).result.current).toBe(false);
  });

  it('condenses past 24px, holds between 4 and 24, and expands under 4', () => {
    const { result } = renderHook(() => useBarScrolled());

    scrollTo(24);
    expect(result.current).toBe(false); // threshold is strictly past 24
    scrollTo(25);
    expect(result.current).toBe(true);
    scrollTo(5);
    expect(result.current).toBe(true);
    scrollTo(4);
    expect(result.current).toBe(false);
  });

  it('reads the current position on mount (a reload mid-page condenses straight away)', () => {
    Object.defineProperty(window, 'scrollY', { value: 300, configurable: true });
    expect(renderHook(() => useBarScrolled()).result.current).toBe(true);
  });

  it('removes its scroll listener on unmount', () => {
    const { result, unmount } = renderHook(() => useBarScrolled());
    unmount();
    scrollTo(300);
    expect(result.current).toBe(false);
  });
});
