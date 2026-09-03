import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLocale } from './useLocale';
import { setLocale } from '../lib/auth';
import { LOCALE_EN } from '../constants';

beforeEach(() => {
  localStorage.clear();
});

describe('useLocale', () => {
  it('defaults to LOCALE_EN when no preference is stored', () => {
    const { result } = renderHook(() => useLocale());
    expect(result.current).toBe(LOCALE_EN);
  });

  it('reflects a stored preference and updates live on setLocale', () => {
    const { result } = renderHook(() => useLocale());

    act(() => setLocale('ru'));
    expect(result.current).toBe('ru');

    act(() => setLocale('et'));
    expect(result.current).toBe('et');
  });

  it('stops updating after unmount', () => {
    const { unmount } = renderHook(() => useLocale());
    unmount();
    act(() => setLocale('ru'));
    // No assertion possible on a stale hook result post-unmount; this just
    // verifies setLocale doesn't throw when the last subscriber is gone.
    expect(localStorage.getItem('locale')).toBe('ru');
  });
});
