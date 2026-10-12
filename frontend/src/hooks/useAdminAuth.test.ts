import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAdminAuth } from './useAdminAuth';
import { setAdminSignedInHint, clearAdminSignedInHint } from '../lib/adminAuth';
import { ADMIN_SIGNED_IN_HINT_KEY } from '../constants/auth';

// Mirrors useOrganizerAuth.test.ts — same subscribe/getSnapshot shape, third
// independent session track.

beforeEach(() => {
  localStorage.clear();
});

describe('useAdminAuth', () => {
  it('reflects the current signed-in state and updates on setAdminSignedInHint/clearAdminSignedInHint', () => {
    const { result } = renderHook(() => useAdminAuth());
    expect(result.current).toBe(false);

    act(() => setAdminSignedInHint());
    expect(result.current).toBe(true);

    act(() => clearAdminSignedInHint());
    expect(result.current).toBe(false);
  });

  it('stops updating after unmount', () => {
    const { unmount } = renderHook(() => useAdminAuth());
    unmount();
    act(() => setAdminSignedInHint());
    expect(localStorage.getItem(ADMIN_SIGNED_IN_HINT_KEY)).not.toBeNull();
  });
});
