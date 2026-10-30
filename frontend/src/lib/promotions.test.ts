import { describe, it, expect } from 'vitest';
import { formatEuro, formatWindow, priceLine, promotionPill, unusedDays, withdrawRefundCents, type PromotionRow } from './promotions';

function row(overrides: Partial<PromotionRow> = {}): PromotionRow {
  return {
    id: 1,
    event_id: 7,
    event_title: 'Jazz Night',
    organizer_name: 'Jazzklubi MTÜ',
    status: 'paid',
    state: 'live',
    paused_reason: null,
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
    refunded_cents: 0,
    invoice_source: 'manual',
    invoice_url: null,
    awaiting_checkout: false,
    checkout_expires_at: null,
    advertiser_legal_name: 'Jazzklubi MTÜ',
    ...overrides,
  };
}

describe('promotionPill', () => {
  it('shows computed live and scheduled for paid rows', () => {
    expect(promotionPill(row()).label).toBe('Live');
    expect(promotionPill(row({ state: 'scheduled' })).label).toBe('Scheduled');
  });

  it('shows a live row the fill gate pauses as Paused with its reason', () => {
    const pill = promotionPill(row({ paused_reason: 'organizer_not_owner' }));
    expect(pill).toEqual({ label: 'Paused', tone: 'attention', reason: 'Paused · claim inactive' });
  });

  it('ignores a pause reason on a scheduled or finished row', () => {
    expect(promotionPill(row({ state: 'scheduled', paused_reason: 'event_ended' })).label).toBe('Scheduled');
    expect(promotionPill(row({ state: 'finished', paused_reason: 'event_ended' })).label).toBe('Finished');
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

describe('awaiting checkout', () => {
  it('shows its own pill with the session expiry instead of the unpaid void line', () => {
    const pill = promotionPill(
      row({ status: 'unpaid', state: 'scheduled', awaiting_checkout: true, checkout_expires_at: '2026-10-17T15:42:00+03:00' }),
    );
    expect(pill.label).toBe('Awaiting checkout');
    expect(pill.reason).toBe('Organizer is in Stripe Checkout · session expires 15:42, voids on its own');
  });
});

describe('withdraw figures', () => {
  it('counts a live Promotion as using today and a scheduled one as fully unused', () => {
    const live = row({ start_date: '2026-10-14', end_date: '2026-10-20', days: 7 });
    expect(unusedDays(live, '2026-10-18')).toBe(2);
    expect(unusedDays(live, '2026-10-20')).toBe(0);
    expect(unusedDays(row({ start_date: '2026-10-21', end_date: '2026-10-25', days: 5 }), '2026-10-18')).toBe(5);
  });

  it('refunds the net share plus VAT, the exact gross for the whole window, nothing when complimentary', () => {
    expect(withdrawRefundCents(row(), 2)).toBe(1240);
    expect(withdrawRefundCents(row(), 7)).toBe(4340);
    expect(withdrawRefundCents(row(), 0)).toBe(0);
    expect(withdrawRefundCents(row({ is_complimentary: true }), 7)).toBe(0);
    expect(withdrawRefundCents(row({ refunded_cents: 4000 }), 7)).toBe(340);
  });
});
