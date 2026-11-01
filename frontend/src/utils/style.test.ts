import { describe, it, expect } from 'vitest';
import { cardAnimationDelayMs, categoryGradient, cx, makeActiveClassMap, shouldFlipPopover } from './style';
import { FALLBACK_GRADIENT } from '../constants/theme';

describe('cx', () => {
  it('joins truthy classes', () => {
    expect(cx('a', 'b', 'c')).toBe('a b c');
  });

  it('filters falsy values', () => {
    expect(cx('a', false, null, undefined, 'b')).toBe('a b');
  });

  it('returns empty string when all falsy', () => {
    expect(cx(false, null, undefined)).toBe('');
  });
});

describe('categoryGradient', () => {
  it('returns gradient for known category', () => {
    const result = categoryGradient(['music']);
    expect(result).toContain('gradient');
    expect(result).not.toBe(FALLBACK_GRADIENT);
  });

  it('returns fallback for unknown category', () => {
    expect(categoryGradient(['unknown_category_xyz'])).toBe(FALLBACK_GRADIENT);
  });

  it('returns fallback for empty array', () => {
    expect(categoryGradient([])).toBe(FALLBACK_GRADIENT);
  });

  it('normalizes case and spaces', () => {
    const result = categoryGradient(['Food Drink']);
    expect(result).toContain('gradient');
    expect(result).not.toBe(FALLBACK_GRADIENT);
  });
});

describe('makeActiveClassMap', () => {
  it('maps signals to class names from styles', () => {
    const styles = { activeLike: 'like-cls', activeDislike: 'dislike-cls', activeBookmark: 'bookmark-cls' };
    const map = makeActiveClassMap(styles);
    expect(map.like).toBe('like-cls');
    expect(map.dislike).toBe('dislike-cls');
    expect(map.bookmark).toBe('bookmark-cls');
  });

  it('throws when a required CSS class is missing', () => {
    const styles = { activeLike: 'like-cls' };
    expect(() => makeActiveClassMap(styles)).toThrow('makeActiveClassMap');
  });
});

describe('shouldFlipPopover', () => {
  it('flips when a wide popover near the right edge would overflow', () => {
    expect(shouldFlipPopover(700, 330, 800, 24)).toBe(true);
  });

  it('does not flip when the trigger is near the left edge', () => {
    expect(shouldFlipPopover(20, 330, 800, 24)).toBe(false);
  });

  it('does not flip exactly at the boundary (viewportWidth - margin)', () => {
    expect(shouldFlipPopover(446, 330, 800, 24)).toBe(false);
  });

  it('flips one pixel past the boundary', () => {
    expect(shouldFlipPopover(447, 330, 800, 24)).toBe(true);
  });
});

describe('cardAnimationDelayMs', () => {
  it('staggers within a page and plateaus after the cap', () => {
    expect(cardAnimationDelayMs(0)).toBe(0);
    expect(cardAnimationDelayMs(3)).toBe(240);
    expect(cardAnimationDelayMs(23)).toBe(640);
  });

  it('restarts on every page so later cards are not held invisible', () => {
    expect(cardAnimationDelayMs(24)).toBe(0);
    expect(cardAnimationDelayMs(24 * 5 + 2)).toBe(160);
  });
});
