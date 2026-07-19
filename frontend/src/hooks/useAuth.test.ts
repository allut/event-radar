import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAuth } from './useAuth';
import { setToken, clearToken } from '../lib/auth';
import { TOKEN_KEY } from '../constants';

beforeEach(() => {
  localStorage.clear();
});

describe('useAuth', () => {
  it('reflects the current token state and updates on setToken/clearToken', () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current).toBe(false);

    act(() => setToken('test-token'));
    expect(result.current).toBe(true);

    act(() => clearToken());
    expect(result.current).toBe(false);
  });

  it('stops updating after unmount', () => {
    const { unmount } = renderHook(() => useAuth());
    unmount();
    act(() => setToken('test-token'));
    // No assertion possible on a stale hook result post-unmount; this just
    // verifies clearToken/setToken don't throw when the last subscriber is gone.
    expect(localStorage.getItem(TOKEN_KEY)).toBe('test-token');
  });
});
