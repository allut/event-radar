import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useToast } from './useToast';
import { SAVE_MSG_CLEAR_DELAY_MS } from '../constants/core';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('useToast', () => {
  it('starts idle', () => {
    const { result } = renderHook(() => useToast());
    expect(result.current.toast.status).toBe('idle');
  });

  it('success auto-clears after the delay', () => {
    const { result } = renderHook(() => useToast());

    act(() => result.current.showToast('success', 'Saved'));
    expect(result.current.toast).toEqual({ status: 'success', message: 'Saved' });

    act(() => vi.advanceTimersByTime(SAVE_MSG_CLEAR_DELAY_MS));
    expect(result.current.toast.status).toBe('idle');
  });

  it('error persists (no auto-clear)', () => {
    const { result } = renderHook(() => useToast());

    act(() => result.current.showToast('error', 'Nope'));
    act(() => vi.advanceTimersByTime(SAVE_MSG_CLEAR_DELAY_MS * 3));

    expect(result.current.toast).toEqual({ status: 'error', message: 'Nope' });
  });
});
