import { describe, it, expect } from 'vitest';
import { toggleCapped } from './list';

describe('toggleCapped', () => {
  it('appends a new value while there is room', () => {
    expect(toggleCapped(['a'], 'b', 3)).toEqual(['a', 'b']);
  });

  it('removes a value that is already present', () => {
    expect(toggleCapped(['a', 'b'], 'a', 3)).toEqual(['b']);
  });

  it('returns the list unchanged once the cap is reached', () => {
    const list = ['a', 'b', 'c'];
    expect(toggleCapped(list, 'd', 3)).toBe(list);
  });

  it('still removes at the cap, and adds nothing when the cap is zero', () => {
    expect(toggleCapped(['a', 'b', 'c'], 'c', 3)).toEqual(['a', 'b']);
    expect(toggleCapped([], 'a', 0)).toEqual([]);
  });
});
