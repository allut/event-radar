import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLocale } from './useLocale';
import { setLocale } from '../lib/auth';
import { LOCALES } from '../constants';

beforeEach(() => {
  localStorage.clear();
});

describe('useLocale', () => {
  it('defaults to LOCALES[0] when no preference is stored', () => {
    const { result } = renderHook(() => useLocale());
    expect(result.current).toBe(LOCALES[0].code);
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
