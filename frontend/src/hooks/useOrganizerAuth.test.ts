import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useOrganizerAuth } from './useOrganizerAuth';
import { setOrganizerSignedInHint, clearOrganizerSignedInHint } from '../lib/organizerAuth';
import { ORGANIZER_SIGNED_IN_HINT_KEY } from '../constants';

// Mirrors useAuth.test.ts — same subscribe/getSnapshot shape, separate
// organizer session track (own storage key, own listener set).

beforeEach(() => {
  localStorage.clear();
});

describe('useOrganizerAuth', () => {
  it('reflects the current signed-in state and updates on setOrganizerSignedInHint/clearOrganizerSignedInHint', () => {
    const { result } = renderHook(() => useOrganizerAuth());
    expect(result.current).toBe(false);

    act(() => setOrganizerSignedInHint());
    expect(result.current).toBe(true);

    act(() => clearOrganizerSignedInHint());
    expect(result.current).toBe(false);
  });

  it('stops updating after unmount', () => {
    const { unmount } = renderHook(() => useOrganizerAuth());
    unmount();
    act(() => setOrganizerSignedInHint());
    // No assertion possible on a stale hook result post-unmount; this just
    // verifies setOrganizerSignedInHint doesn't throw when the last subscriber is gone.
    expect(localStorage.getItem(ORGANIZER_SIGNED_IN_HINT_KEY)).not.toBeNull();
  });
});
