import { describe, it, expect, vi, afterEach } from 'vitest';
import { storageGet, storageSet, storageRemove } from './storage';

describe('storage helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('round-trips a value', () => {
    storageSet('k', 'v');
    expect(storageGet('k')).toBe('v');
    storageRemove('k');
    expect(storageGet('k')).toBeNull();
  });

  it('degrades silently when storage throws', () => {
    const boom = () => { throw new DOMException('blocked', 'SecurityError'); };
    vi.spyOn(localStorage, 'getItem').mockImplementation(boom);
    vi.spyOn(localStorage, 'setItem').mockImplementation(boom);
    vi.spyOn(localStorage, 'removeItem').mockImplementation(boom);
    expect(storageGet('k')).toBeNull();
    expect(() => storageSet('k', 'v')).not.toThrow();
    expect(() => storageRemove('k')).not.toThrow();
  });
});
