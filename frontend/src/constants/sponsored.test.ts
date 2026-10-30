import { afterEach, describe, it, expect, vi } from 'vitest';
import { FAQ_PAID_ID_PREFIX, RANKING_PAID_SLOTS_ID, SPONSORED_RANKING_TARGET, isPromotionsSlotsEnabled } from './sponsored';

afterEach(() => vi.unstubAllEnvs());

describe('sponsored constants', () => {
  it('points the "Why?" link at the paid-slots anchor, never an `ads` one', () => {
    expect(RANKING_PAID_SLOTS_ID).toBe('paid-slots');
    expect(SPONSORED_RANKING_TARGET).toBe('/ranking#paid-slots');
    expect(FAQ_PAID_ID_PREFIX).toBe('paid-');
  });

  it('reads the slots flag from the build env, off unless exactly "true"', () => {
    expect(isPromotionsSlotsEnabled()).toBe(false);
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'true');
    expect(isPromotionsSlotsEnabled()).toBe(true);
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'false');
    expect(isPromotionsSlotsEnabled()).toBe(false);
  });
});
