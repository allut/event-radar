import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useScrollLock } from './useScrollLock';

describe('useScrollLock', () => {
  it('locks body scroll while locked and restores the previous value after', () => {
    document.body.style.overflow = 'auto';
    const { rerender } = renderHook(({ locked }) => useScrollLock(locked), { initialProps: { locked: false } });
    expect(document.body.style.overflow).toBe('auto');

    rerender({ locked: true });
    expect(document.body.style.overflow).toBe('hidden');

    rerender({ locked: false });
    expect(document.body.style.overflow).toBe('auto');
    document.body.style.overflow = '';
  });

  it('restores on unmount', () => {
    const { unmount } = renderHook(() => useScrollLock(true));
    expect(document.body.style.overflow).toBe('hidden');
    unmount();
    expect(document.body.style.overflow).toBe('');
  });
});
