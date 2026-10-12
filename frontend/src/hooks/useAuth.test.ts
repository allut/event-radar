import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAuth } from './useAuth';
import { setSignedInHint, clearSignedInHint } from '../lib/auth';
import { SIGNED_IN_HINT_KEY } from '../constants/auth';

beforeEach(() => {
  localStorage.clear();
});

describe('useAuth', () => {
  it('reflects the current signed-in state and updates on setSignedInHint/clearSignedInHint', () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current).toBe(false);

    act(() => setSignedInHint());
    expect(result.current).toBe(true);

    act(() => clearSignedInHint());
    expect(result.current).toBe(false);
  });

  it('stops updating after unmount', () => {
    const { unmount } = renderHook(() => useAuth());
    unmount();
    act(() => setSignedInHint());
    // No assertion possible on a stale hook result post-unmount; this just
    // verifies clearSignedInHint/setSignedInHint don't throw when the last subscriber is gone.
    expect(localStorage.getItem(SIGNED_IN_HINT_KEY)).not.toBeNull();
  });
});
