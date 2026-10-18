import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminPromotionDetail from './AdminPromotionDetail';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { ApiError, adminApi } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);
const mockPatch = vi.mocked(adminApi.patch);

const NO_ACTIONS = {
  mark_paid: false,
  edit: false,
  edit_scope: null,
  repoint: false,
  end: false,
  void: false,
  refund: false,
  refundable_cents: 0,
};

function detail(overrides: Record<string, unknown> = {}, actions: Record<string, unknown> = {}) {
  return {
    id: 5,
    event_id: 7,
    event_title: 'Noblessner Food Fest',
    organizer_id: 3,
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
    invoice_reference: 'ER-M-0007',
    invoice_source: 'admin',
    advertiser_legal_name: 'Noblessner Events OÜ',
    advertiser_registry_code: '12345678',
    billing_email: 'info@noblessner.ee',
    granted_by: 'admin',
    paid_at: '2026-10-13T11:20:00+03:00',
    ended_at: null,
    end_reason: null,
    end_note: null,
    refunded_cents: 0,
    refund_note: null,
    invoice_url: null,
    awaiting_checkout: false,
    checkout_expires_at: null,
    refund_prefill: null,
    created_at: '2026-10-13T11:00:00+03:00',
    event: { id: 7, title: 'Noblessner Food Fest', starts_at: '2026-10-24T12:00:00+03:00', ends_at: null, last_day: '2026-10-24', venue_name: 'Noblessner' },
    actions: { ...NO_ACTIONS, edit: true, edit_scope: 'end_date', repoint: true, end: true, refund: true, refundable_cents: 4340, ...actions },
    repoint_candidates: [{ event_id: 9, title: 'Noblessner Food Fest, evening', last_day: '2026-10-24' }],
    snapshots: [
      {
        id: 1,
        taken_at: '2026-10-13T11:20:00+03:00',
        trigger: 'mark_paid',
        event_id: 7,
        title: { et: 'Noblessneri toidufestival', en: 'Noblessner Food Fest', ru: 'Фестиваль еды' },
        description_excerpt: 'Street food by the sea.',
        image_url: null,
        venue_name: 'Noblessner',
        event_starts_at: '2026-10-24T12:00:00+03:00',
        event_ends_at: null,
        start_date: '2026-10-14',
        end_date: '2026-10-20',
        net_price_cents: 3500,
        vat_rate_percent: '24.00',
        label_text: 'REKLAAM · Noblessner Events OÜ',
      },
    ],
    audit: [
      { action: 'promotion_mark_paid', result: 'ok', created_at: '2026-10-13T11:20:00+03:00' },
      { action: 'promotion_grant', result: 'ok', created_at: '2026-10-13T11:00:00+03:00' },
    ],
    ...overrides,
  };
}

function stat(day: string, over: Record<string, unknown> = {}) {
  return {
    day,
    gate_outcome: 'shown',
    gate_reason: null,
    explore_served: 0,
    daily5_placed: 0,
    digest_sent: 0,
    web_opens: 0,
    digest_opens: 0,
    slot_dislikes: 0,
    ...over,
  };
}

function serve(d: ReturnType<typeof detail>, days: unknown[] = []) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.endsWith('/daily-stats')) return { promotion_id: d.id, today: '2026-10-17', days };
    if (path === '/admin/promotions/5') return d;
    throw new Error(`unexpected ${path}`);
  });
}

const UNPAID = {
  status: 'unpaid',
  state: 'scheduled',
  start_date: '2026-10-24',
  end_date: '2026-10-30',
  invoice_reference: null,
  paid_at: null,
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
});

describe('AdminPromotionDetail', () => {
  it('shows the computed state, window, record and audit', async () => {
    serve(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    expect(await screen.findByRole('heading', { name: 'Noblessner Food Fest' })).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('14–20 Oct')).toBeInTheDocument();
    const record = screen.getByRole('region', { name: 'Commercial record' });
    expect(within(record).getByText('12345678')).toBeInTheDocument();
    expect(within(record).getByText('€43.40')).toBeInTheDocument();
    expect(within(record).getByText('ER-M-0007')).toBeInTheDocument();
    const audit = screen.getByRole('region', { name: 'Audit' });
    expect(within(audit).getAllByRole('listitem')).toHaveLength(2);
    expect(within(audit).getByText('promotion_mark_paid')).toBeInTheDocument();
  });

  it('enables each action from the API flags', async () => {
    serve(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await screen.findByRole('heading', { name: 'Noblessner Food Fest' });
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'End early' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Record refund' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Mark paid' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Void' })).toBeDisabled();
  });

  it('shows the per-day table with totals and the served-is-not-seen note', async () => {
    serve(detail(), [
      stat('2026-10-14', { explore_served: 31, daily5_placed: 12, web_opens: 3 }),
      stat('2026-10-15', { explore_served: 44, daily5_placed: 15, web_opens: 5, slot_dislikes: 1 }),
      stat('2026-10-16', { gate_outcome: 'paused', gate_reason: 'organizer_not_owner' }),
    ]);
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    const delivery = await screen.findByRole('region', { name: 'Delivery · per day' });
    const rows = await within(delivery).findAllByRole('row');
    expect(rows).toHaveLength(5); // header + 3 days + total
    expect(within(rows[4]).getByText('75')).toBeInTheDocument();
    expect(within(rows[4]).getByText('27')).toBeInTheDocument();
    expect(within(rows[3]).getByText(/Paused · claim inactive/)).toBeInTheDocument();
    expect(within(delivery).getByText(/“Served” is not “seen”/)).toBeInTheDocument();
  });

  it('explains the empty delivery table', async () => {
    serve(detail(UNPAID));
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    expect(await screen.findByText(/No complete days yet/)).toBeInTheDocument();
  });

  it('shows the not-showing reason for an unpaid Promotion and an ended one', async () => {
    serve(detail(UNPAID));
    const { unmount } = renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    expect(await screen.findByText('Awaiting payment')).toBeInTheDocument();
    expect(screen.getByText(/voids when Sat 24 Oct begins/)).toBeInTheDocument();
    unmount();

    serve(detail({ status: 'ended_early', state: 'finished', end_reason: 'admin', end_note: 'Content policy breach' }));
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    expect(await screen.findByText('Ended early')).toBeInTheDocument();
    expect(screen.getByText('Ended: Content policy breach')).toBeInTheDocument();
  });

  it('marks paid with the invoice reference through an inline panel', async () => {
    serve(detail(UNPAID, { mark_paid: true, void: true, edit_scope: 'full' }));
    mockPost.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Mark paid' }));
    await userEvent.type(screen.getByLabelText('Invoice reference (optional)'), 'ER-M-0009');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm mark paid' }));
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/mark-paid', { invoice_reference: 'ER-M-0009' });
  });

  it('requires a reason before ending early and posts it', async () => {
    serve(detail());
    mockPost.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'End early' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm end early' }));
    expect(screen.getByText(/Give a reason/)).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/Reason/), 'Content policy breach');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm end early' }));
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/end', { reason: 'Content policy breach' });
  });

  it('voids with a reason', async () => {
    serve(detail(UNPAID, { void: true, end: false, mark_paid: true }));
    mockPost.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Void' }));
    await userEvent.type(screen.getByLabelText(/Reason/), 'Never paid');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm void' }));
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/void', { reason: 'Never paid' });
  });

  it('shortens a live window: only the end date is editable and only it is sent', async () => {
    // Pin only Date so the "never before today" bound on the end date stays stable.
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 9, 17, 12) });
    serve(detail());
    mockPatch.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByRole('heading', { name: 'Shorten live window' })).toBeInTheDocument();
    expect(screen.getByLabelText('Start date')).toBeDisabled();
    expect(screen.queryByLabelText('Advertiser legal name')).not.toBeInTheDocument();
    const end = screen.getByLabelText('End date');
    await userEvent.type(end, '2026-10-18', { initialSelectionStart: 0, initialSelectionEnd: 10 });
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(mockPatch).toHaveBeenCalledWith('/admin/promotions/5', { end_date: '2026-10-18' });
    vi.useRealTimers();
  });

  it('edits advertiser details before the start date, sending only changes', async () => {
    serve(detail(UNPAID, { edit_scope: 'full', mark_paid: true, void: true, end: false }));
    mockPatch.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const name = screen.getByLabelText('Advertiser legal name');
    await userEvent.clear(name);
    await userEvent.type(name, 'New OÜ');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(mockPatch).toHaveBeenCalledWith('/admin/promotions/5', { advertiser_legal_name: 'New OÜ' });
  });

  it('re-points to a candidate event', async () => {
    serve(detail());
    mockPost.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Re-point' }));
    await userEvent.selectOptions(screen.getByLabelText(/Same Organizer, same duplicate group/), '9');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm re-point' }));
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/repoint', { event_id: 9 });
  });

  it('records a gross refund in cents, prefilled with the refundable amount, with a required note', async () => {
    serve(detail());
    mockPost.mockResolvedValue(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Record refund' }));
    const amount = screen.getByLabelText(/Amount/);
    expect(amount).toHaveValue('43.40');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm refund' }));
    expect(screen.getByText('A note is required.')).toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, '12.50');
    await userEvent.type(screen.getByLabelText(/Note/), 'Three unused days');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm refund' }));
    expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/refund', { amount_cents: 1250, note: 'Three unused days' });
  });

  it('refuses a refund above the refundable amount', async () => {
    serve(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Record refund' }));
    const amount = screen.getByLabelText(/Amount/);
    await userEvent.clear(amount);
    await userEvent.type(amount, '99');
    await userEvent.type(screen.getByLabelText(/Note/), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm refund' }));
    expect(screen.getByText('Enter an amount up to €43.40.')).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows the server refusal inside the open panel', async () => {
    serve(detail());
    mockPost.mockRejectedValue(new ApiError(409, 'Only paid Promotions can end early.', 'wrong_status'));
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    await userEvent.click(await screen.findByRole('button', { name: 'End early' }));
    await userEvent.type(screen.getByLabelText(/Reason/), 'Policy');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm end early' }));
    expect(await screen.findByText('Only paid Promotions can end early.')).toBeInTheDocument();
  });

  it('lists content snapshots with their trigger', async () => {
    serve(detail());
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    const snaps = await screen.findByRole('region', { name: /Content snapshots/ });
    expect(within(snaps).getByText('REKLAAM · Noblessner Events OÜ')).toBeInTheDocument();
    expect(within(snaps).getByText(/mark paid/)).toBeInTheDocument();
    expect(within(snaps).getByText(/Noblessneri toidufestival/)).toBeInTheDocument();
  });

  it('shows an error state when the Promotion cannot be loaded', async () => {
    mockGet.mockRejectedValue(new ApiError(404, 'Promotion not found'));
    renderWithProviders(<AdminPromotionDetail promotionId="5" />);
    expect(await screen.findByText('Couldn’t load this Promotion.')).toBeInTheDocument();
  });

  describe('Stripe payments (#618, #619)', () => {
    const STRIPE_PAID = {
      invoice_source: 'stripe',
      invoice_reference: 'ER-0042',
      invoice_url: 'https://invoice.stripe.com/i/abc',
      refund_prefill: {
        mode: 'stripe',
        unused_days: 2,
        paused_days: 1,
        gross_per_day_cents: 620,
        suggested_cents: 1860,
        remaining_cents: 4340,
      },
    };

    it('marks a card payment with the Stripe chip, the hosted invoice link and the Issue refund button', async () => {
      serve(detail(STRIPE_PAID));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      expect(await screen.findByText('Paid by card via Stripe')).toBeInTheDocument();
      const record = screen.getByRole('region', { name: 'Commercial record' });
      const link = within(record).getByRole('link', { name: /ER-0042/ });
      expect(link).toHaveAttribute('href', 'https://invoice.stripe.com/i/abc');
      expect(within(record).getByText('Stripe card')).toBeInTheDocument();
      expect(within(record).getByText('2 / 1')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Issue refund' })).toBeEnabled();
      expect(screen.getByText(/credit note against ER-0042/)).toBeInTheDocument();
    });

    it('prefills the refund with (unused + paused) days x the price paid per day and issues it', async () => {
      serve(detail(STRIPE_PAID));
      mockPost.mockResolvedValue(detail(STRIPE_PAID));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await userEvent.click(await screen.findByRole('button', { name: 'Issue refund' }));
      expect(screen.getByText('Suggested: €18.60')).toBeInTheDocument();
      expect(screen.getByText(/\(2 unused \+ 1 paused\) days × €6\.20 per day = €18\.60/)).toBeInTheDocument();
      expect(screen.getByLabelText('Amount (gross, €)')).toHaveValue('18.60');
      const confirm = screen.getByRole('button', { name: 'Issue refund of €18.60' });

      await userEvent.click(confirm);
      expect(screen.getByRole('alert')).toHaveTextContent('A note is required.');
      expect(mockPost).not.toHaveBeenCalled();

      const amount = screen.getByLabelText('Amount (gross, €)');
      await userEvent.clear(amount);
      await userEvent.type(amount, '12.40');
      expect(screen.getByRole('button', { name: 'Issue refund of €12.40' })).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText('Note (required)'), 'Goodwill after pause');
      await userEvent.click(screen.getByRole('button', { name: 'Issue refund of €12.40' }));
      expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/refund', { amount_cents: 1240, note: 'Goodwill after pause' });
    });

    it('shows a Stripe refusal inside the refund panel', async () => {
      serve(detail(STRIPE_PAID));
      mockPost.mockRejectedValue(new ApiError(502, 'Stripe could not issue the refund.'));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await userEvent.click(await screen.findByRole('button', { name: 'Issue refund' }));
      await userEvent.type(screen.getByLabelText('Note (required)'), 'Test');
      await userEvent.click(screen.getByRole('button', { name: /^Issue refund of/ }));
      expect(await screen.findByText('Stripe could not issue the refund.')).toBeInTheDocument();
    });

    it('keeps a bank-paid refund record-only, prefilled from the server suggestion', async () => {
      serve(
        detail({ refund_prefill: { mode: 'manual', unused_days: 5, paused_days: 0, gross_per_day_cents: 620, suggested_cents: 3100, remaining_cents: 4340 } }),
      );
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await userEvent.click(await screen.findByRole('button', { name: 'Record refund' }));
      expect(screen.getByText('Suggested: €31.00')).toBeInTheDocument();
      expect(screen.getByText(/Record-only: this does not move money/)).toBeInTheDocument();
      expect(screen.getByLabelText('Amount (gross, €)')).toHaveValue('31.00');
      expect(screen.getByRole('button', { name: 'Confirm refund' })).toBeInTheDocument();
    });

    it('shows an open checkout as awaiting, offers only Void and never Mark paid', async () => {
      serve(
        detail(
          { ...UNPAID, invoice_source: 'stripe', awaiting_checkout: true, checkout_expires_at: '2026-10-17T15:42:00+03:00' },
          { mark_paid: true, void: true, edit_scope: 'full', end: false, refund: false, refundable_cents: 0 },
        ),
      );
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      expect(await screen.findByText('Awaiting checkout')).toBeInTheDocument();
      expect(screen.getByText('Stripe Checkout open')).toBeInTheDocument();
      expect(screen.getByText(/The session expires 15:42; This voids on its own/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Mark paid' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Void' })).toBeEnabled();
      expect(screen.getByText('Issued when Stripe confirms payment')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Void' }));
      expect(screen.getByText(/also expires its Stripe session/)).toBeInTheDocument();
    });
  });

  describe('Withdraw (#620)', () => {
    it('withdraws a paid Promotion from its page', async () => {
      serve(detail());
      mockPost.mockResolvedValue(detail({ status: 'ended_early', state: 'finished' }, { end: false }));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await userEvent.click(await screen.findByRole('button', { name: 'Withdraw' }));
      expect(screen.getByText(/feature_withdrawn/)).toBeInTheDocument();
      const panel = screen.getByRole('heading', { name: 'Withdraw this Promotion' }).closest('form') as HTMLElement;
      await userEvent.click(within(panel).getByRole('button', { name: 'Withdraw' }));
      expect(mockPost).toHaveBeenCalledWith('/admin/promotions/5/withdraw', {});
    });

    it('words the slots_still_enabled 409 with the runbook step', async () => {
      serve(detail());
      mockPost.mockRejectedValue(new ApiError(409, 'slots_still_enabled'));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await userEvent.click(await screen.findByRole('button', { name: 'Withdraw' }));
      const panel = screen.getByRole('heading', { name: 'Withdraw this Promotion' }).closest('form') as HTMLElement;
      await userEvent.click(within(panel).getByRole('button', { name: 'Withdraw' }));
      expect(await within(panel).findByText(/Slots are still enabled\. Turn PROMOTIONS_SLOTS_ENABLED off in Render/)).toBeInTheDocument();
    });

    it('offers Withdraw only while the server allows ending a paid Promotion', async () => {
      serve(detail(UNPAID, { end: false, mark_paid: true, void: true, refund: false }));
      renderWithProviders(<AdminPromotionDetail promotionId="5" />);
      await screen.findByText('Awaiting payment');
      expect(screen.getByRole('button', { name: 'Withdraw' })).toBeDisabled();
    });
  });
});
