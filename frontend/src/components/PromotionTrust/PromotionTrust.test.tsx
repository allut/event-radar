import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromotionTrust from './PromotionTrust';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { ApiError, adminApi } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

function period(overrides: Record<string, unknown> = {}) {
  return {
    reports_on_promoted: 0,
    reports_resolved: 0,
    promotions_taken_down: 0,
    consents_granted: 41,
    consent_withdrawals: {
      total: 5,
      by_source: { settings: 2, email_link: 1, digest_unsubscribe: 1, wording_change: 0, account_deletion: 1 },
    },
    slots_served: 9810,
    slots_served_by_surface: { explore: 6120, daily5: 1480, digest: 2210 },
    web_opens: 312,
    slot_dislikes: 2,
    complaints: 1,
    ...overrides,
  };
}

function trust(rolling: Record<string, unknown> = {}, launch: Record<string, unknown> = {}, recent: unknown[] = []) {
  return {
    as_of: '2026-10-18T10:00:00+03:00',
    window_days: 28,
    window_start: '2026-09-20',
    current: { live_promotions: 3, consenters: 214 },
    periods: {
      rolling_4_weeks: period(rolling),
      since_launch: period({ consents_granted: 96, slots_served: 19600, complaints: 2, ...launch }),
    },
    recent_complaints: recent,
  };
}

function promo(overrides: Record<string, unknown> = {}) {
  return {
    id: 12,
    event_id: 7,
    event_title: 'Noblessner Food Fest',
    organizer_name: 'Noblessner Events OÜ',
    status: 'paid',
    state: 'live',
    start_date: '2026-10-14',
    end_date: '2026-10-20',
    days: 7,
    net_price_cents: 3500,
    vat_rate_percent: '24.00',
    vat_cents: 840,
    gross_price_cents: 4340,
    is_complimentary: false,
    complimentary_note: null,
    invoice_reference: 'ER-0042',
    refunded_cents: 0,
    invoice_source: 'stripe',
    invoice_url: null,
    awaiting_checkout: false,
    checkout_expires_at: null,
    advertiser_legal_name: 'Noblessner Events OÜ',
    ...overrides,
  };
}

function route(data: unknown, live: unknown[] = [], scheduled: unknown[] = []) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/admin/promotions/trust')) return data;
    if (path.includes('state=live')) return { today: '2026-10-18', promotions: live };
    if (path.includes('state=scheduled')) return { today: '2026-10-18', promotions: scheduled };
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('Trust panel', () => {
  it('shows the denominators and both periods with withdrawals by source and slots by surface', async () => {
    route(trust());
    renderWithProviders(<PromotionTrust />);
    const tile = (await screen.findByText('Current consenters')).parentElement as HTMLElement;
    expect(within(tile).getByText('214')).toBeInTheDocument();
    expect(screen.getByText('Live Promotions').parentElement).toHaveTextContent('3');
    expect(screen.getAllByText('Complaints logged')[0].parentElement).toHaveTextContent('2');

    const rolling = screen.getByText('Rolling 4 weeks').closest('div')!.parentElement as HTMLElement;
    expect(within(rolling).getByText(/^20 Sept? – 18 Oct$/)).toBeInTheDocument();
    expect(within(rolling).getByText('Settings toggle').nextSibling).toHaveTextContent('2');
    expect(within(rolling).getByText('Slot email link').nextSibling).toHaveTextContent('1');
    expect(within(rolling).getByText('Explore').nextSibling).toHaveTextContent('6,120');
    expect(within(rolling).getByText('9,810')).toBeInTheDocument();
    expect(within(rolling).getByText('admin-only')).toBeInTheDocument();

    const launch = screen.getByText('Since launch').closest('div')!.parentElement as HTMLElement;
    expect(within(launch).getByText('since first sale')).toBeInTheDocument();
    expect(within(launch).getByText('96')).toBeInTheDocument();
    expect(within(launch).getByText('19,600')).toBeInTheDocument();
  });

  it('reports no stop-selling condition on healthy figures', async () => {
    route(trust());
    renderWithProviders(<PromotionTrust />);
    expect(await screen.findByText('No stop-selling condition holds')).toBeInTheDocument();
    expect(screen.getAllByText('Clear')).toHaveLength(4);
    expect(screen.queryByText('Tripped')).toBeNull();
  });

  it('flags every tripwire from the rolling-4-weeks figures and names the Stop selling step', async () => {
    route(
      trust({
        consents_granted: 4,
        consent_withdrawals: { total: 9, by_source: { settings: 4, email_link: 3 } },
        web_opens: 3,
        slot_dislikes: 12,
        complaints: 3,
        reports_on_promoted: 3,
        promotions_taken_down: 2,
      }),
    );
    renderWithProviders(<PromotionTrust />);
    expect(await screen.findByText('4 of 4 stop-selling conditions hold')).toBeInTheDocument();
    expect(screen.getAllByText('Tripped')).toHaveLength(4);
    expect(screen.getByText('7 withdrawals (settings + slot link) vs 4 new consents')).toBeInTheDocument();
    expect(screen.getByText('12 dislikes vs 3 web opens')).toBeInTheDocument();
    expect(screen.getByText(/3 logged \(check the names below/)).toBeInTheDocument();
    expect(screen.getByText('2 upheld, 3 reports in all')).toBeInTheDocument();
    expect(screen.getByText(/set PROMOTIONS_OFFER_ENABLED and PROMOTIONS_CHECKOUT_ENABLED off/)).toBeInTheDocument();
  });

  it('does not trip withdrawals below the minimum of 3 even when they outnumber consents', async () => {
    route(trust({ consents_granted: 0, consent_withdrawals: { total: 2, by_source: { settings: 2 } }, slot_dislikes: 2, web_opens: 0 }));
    renderWithProviders(<PromotionTrust />);
    expect(await screen.findByText('No stop-selling condition holds')).toBeInTheDocument();
  });
});

describe('Complaint logger', () => {
  it('requires a note, then posts the complaint and refreshes the panel', async () => {
    route(trust());
    mockPost.mockResolvedValue({ logged: true });
    renderWithProviders(<PromotionTrust />);
    await userEvent.click(await screen.findByRole('button', { name: 'Log complaint' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A note is required.');
    expect(mockPost).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText('Complainant (optional)'), 'maria.k@example.ee');
    await userEvent.type(screen.getByLabelText('Note (required)'), 'The promoted card looked like a normal listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Log complaint' }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/admin/promotions/complaints', {
        source: 'email',
        complainant: 'maria.k@example.ee',
        note: 'The promoted card looked like a normal listing.',
      }),
    );
    expect(await screen.findByText('Complaint logged and counted above.')).toBeInTheDocument();
    expect(screen.getByLabelText('Note (required)')).toHaveValue('');
    // The panel refetches so the new count shows.
    await waitFor(() => expect(mockGet.mock.calls.filter(([p]) => p === '/admin/promotions/trust').length).toBeGreaterThan(1));
  });

  it('lists the recent complaints with source and complainant', async () => {
    route(
      trust({}, {}, [
        { id: 3, created_at: '2026-10-16T18:02:00+03:00', source: 'email', complainant: 'Kalle T.', note: 'Why am I getting ads in the digest?' },
        { id: 1, created_at: '2026-10-03T09:31:00+03:00', source: 'contact_form', complainant: null, note: 'Looked like a normal listing.' },
      ]),
    );
    renderWithProviders(<PromotionTrust />);
    const first = (await screen.findByText('Why am I getting ads in the digest?')).closest('li') as HTMLElement;
    expect(within(first).getByText('Email')).toBeInTheDocument();
    expect(within(first).getByText('Kalle T.')).toBeInTheDocument();
    const second = screen.getByText('Looked like a normal listing.').closest('li') as HTMLElement;
    expect(within(second).getByText('Contact form')).toBeInTheDocument();
    expect(within(second).getByText('No name given')).toBeInTheDocument();
  });
});

describe('Withdraw', () => {
  const live = [promo(), promo({ id: 13, event_title: 'Kino Sõprus Retro Night', is_complimentary: true, net_price_cents: 0, vat_cents: 0, gross_price_cents: 0, invoice_source: 'manual' })];
  const scheduled = [
    promo({ id: 14, event_title: 'Lauluväljak Autumn Run', state: 'scheduled', start_date: '2026-10-21', end_date: '2026-10-25', days: 5, net_price_cents: 2500, invoice_source: 'manual' }),
    promo({ id: 15, event_title: 'Unpaid thing', status: 'unpaid', state: 'scheduled', start_date: '2026-10-22', end_date: '2026-10-25', days: 4 }),
  ];

  it('lists paid live and scheduled Promotions with unused days and the refund Withdraw will record', async () => {
    route(trust(), live, scheduled);
    renderWithProviders(<PromotionTrust />);
    const food = (await screen.findByText('Noblessner Food Fest')).closest('tr') as HTMLElement;
    // Live, ends 20 Oct, today 18 Oct: 2 unused days of 7 => 2/7 of €35.00 net + VAT.
    expect(within(food).getByText('2')).toBeInTheDocument();
    expect(within(food).getByText('€12.40')).toBeInTheDocument();
    expect(within(food).getByText('Stripe')).toBeInTheDocument();
    const kino = screen.getByText('Kino Sõprus Retro Night').closest('tr') as HTMLElement;
    expect(within(kino).getByText('€0.00 (nothing to refund)')).toBeInTheDocument();
    const scheduledRow = screen.getByText('Lauluväljak Autumn Run').closest('tr') as HTMLElement;
    expect(within(scheduledRow).getByText('€31.00')).toBeInTheDocument();
    expect(screen.queryByText('Unpaid thing')).toBeNull();
    expect(screen.getByRole('button', { name: 'Withdraw all (3)' })).toBeInTheDocument();
  });

  it('shows the slots_still_enabled refusal on the row when the flag is still on', async () => {
    route(trust(), live, scheduled);
    mockPost.mockRejectedValue(new ApiError(409, 'slots_still_enabled'));
    renderWithProviders(<PromotionTrust />);
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw Noblessner Food Fest' }));
    expect(await screen.findByText('Slots are still enabled. Turn PROMOTIONS_SLOTS_ENABLED off in Render and restart, then try again.')).toBeInTheDocument();
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/12/withdraw', {});
    expect(screen.queryByText(/Withdrew/)).toBeNull();
  });

  it('withdraws one Promotion, records the refund and reminds to refund the card in Stripe', async () => {
    route(trust(), live, scheduled);
    mockPost.mockResolvedValue({ id: 12, refunded_cents: 1240 });
    renderWithProviders(<PromotionTrust />);
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw Noblessner Food Fest' }));
    const done = (await screen.findByText('Withdrew 1 Promotion · €12.40 refunds recorded')).parentElement as HTMLElement;
    expect(within(done).getByText(/2 unused days · €12\.40 recorded/)).toBeInTheDocument();
    expect(within(done).getByText(/Issue the card refund in Stripe for Noblessner Food Fest/)).toBeInTheDocument();
  });

  it('needs the confirmation tick for Withdraw all, refuses on 409, then lists withdrawn and skipped', async () => {
    route(trust(), live, scheduled);
    mockPost.mockRejectedValueOnce(new ApiError(409, 'slots_still_enabled'));
    renderWithProviders(<PromotionTrust />);
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw all (3)' }));
    const panel = screen.getByRole('heading', { name: 'Withdraw all 3 paid Promotions' }).parentElement as HTMLElement;
    await userEvent.click(within(panel).getByRole('button', { name: 'Withdraw all' }));
    expect(within(panel).getByRole('alert')).toHaveTextContent('Tick the box to confirm.');
    expect(mockPost).not.toHaveBeenCalled();

    await userEvent.click(within(panel).getByLabelText(/I turned the slots flag off/));
    await userEvent.click(within(panel).getByRole('button', { name: 'Withdraw all' }));
    expect(await within(panel).findByText(/Slots are still enabled/)).toBeInTheDocument();

    mockPost.mockResolvedValueOnce({
      withdrawn: [
        { id: 12, event_id: 7, unused_days: 2, refund_cents: 1240, refunded_cents: 1240 },
        { id: 13, event_id: 7, unused_days: 3, refund_cents: 0, refunded_cents: 0 },
      ],
      skipped: [{ id: 14, code: 'invalid_transition' }],
    });
    await userEvent.click(within(panel).getByRole('button', { name: 'Withdraw all' }));
    expect(await screen.findByText('Withdrew 2 Promotions · €12.40 refunds recorded')).toBeInTheDocument();
    expect(screen.getByText('Skipped 1')).toBeInTheDocument();
    expect(screen.getByText('invalid_transition')).toBeInTheDocument();
    expect(mockPost).toHaveBeenLastCalledWith('/admin/promotions/withdraw-all', {});
  });
});
