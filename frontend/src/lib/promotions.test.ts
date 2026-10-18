import { describe, it, expect } from 'vitest';
import { formatEuro, formatWindow, priceLine, promotionPill, type PromotionRow } from './promotions';

function row(overrides: Partial<PromotionRow> = {}): PromotionRow {
  return {
    id: 1,
    event_id: 7,
    event_title: 'Jazz Night',
    organizer_name: 'Jazzklubi MTÜ',
    status: 'paid',
    state: 'live',
    start_date: '2026-10-17',
    end_date: '2026-10-23',
    days: 7,
    net_price_cents: 3500,
    vat_rate_percent: '24.00',
    vat_cents: 840,
    gross_price_cents: 4340,
    is_complimentary: false,
    complimentary_note: null,
    invoice_reference: null,
    advertiser_legal_name: 'Jazzklubi MTÜ',
    ...overrides,
  };
}

describe('promotionPill', () => {
  it('shows computed live and scheduled for paid rows', () => {
    expect(promotionPill(row()).label).toBe('Live');
    expect(promotionPill(row({ state: 'scheduled' })).label).toBe('Scheduled');
  });

  it('flags an unpaid row as awaiting payment with the void-at-start reason', () => {
    const pill = promotionPill(row({ status: 'unpaid', state: 'scheduled', start_date: '2026-10-24' }));
    expect(pill.label).toBe('Awaiting payment');
    expect(pill.reason).toBe('Unpaid · voids when Sat 24 Oct begins');
  });

  it('shows stored void and ended-early statuses as their own finished pills', () => {
    expect(promotionPill(row({ status: 'void', state: 'finished' })).label).toBe('Void');
    expect(promotionPill(row({ status: 'ended_early', state: 'finished' })).label).toBe('Ended early');
    expect(promotionPill(row({ state: 'finished' })).label).toBe('Finished');
  });
});

describe('formatting', () => {
  it('formats euro cents and the price line', () => {
    expect(formatEuro(3500)).toBe('€35.00');
    expect(priceLine({ net_cents: 3500, vat_cents: 840, gross_cents: 4340 })).toBe(
      '€35.00 + €8.40 VAT = €43.40',
    );
  });

  it('formats a window within one month and across months', () => {
    expect(formatWindow('2026-10-12', '2026-10-18')).toBe('12–18 Oct');
    expect(formatWindow('2026-10-24', '2026-11-02')).toBe('24 Oct – 2 Nov');
  });
});
