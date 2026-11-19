import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromotionRequests from './PromotionRequests';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { ApiError, adminApi } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

function request(overrides: Record<string, unknown> = {}) {
  return {
    id: 41,
    event_id: 7,
    event_title: 'Tallinn Jazz Night',
    organizer_id: 3,
    organizer_name: 'Example Jazz Club MTÜ',
    organizer_email: 'info@jazzclub.example',
    status: 'pending',
    start_date: '2026-10-24',
    end_date: '2026-10-30',
    days: 7,
    price: { net_cents: 3500, vat_cents: 840, gross_cents: 4340 },
    advertiser_legal_name: 'Example Jazz Club MTÜ',
    advertiser_registry_code: '80123456',
    billing_email: 'info@jazzclub.example',
    note: 'Could the Promotion start a day earlier if possible?',
    decline_reason: null,
    promotion_restriction: 'none',
    not_eligible_reason: null,
    created_at: '2026-10-16T09:00:00+03:00',
    resolved_at: null,
    ...overrides,
  };
}

function queue(requests: unknown[], pending = requests.length) {
  return { pending_count: pending, requests, total: requests.length, limit: 50, offset: 0, has_more: false };
}

const context = {
  event_id: 7,
  event_title: 'Tallinn Jazz Night',
  promotion_restriction: 'none',
  owner: { organizer_id: 3, name: 'Example Jazz Club MTÜ', email: 'info@jazzclub.example' },
  prefill: { advertiser_legal_name: 'Example Jazz Club MTÜ', billing_email: 'info@jazzclub.example' },
  today: '2026-10-18',
  earliest_start: '2026-10-19',
  event_last_day: '2026-10-30',
  rules: { min_days: 3, max_days: 14, cap: 5, cap_strip_days: 14 },
  pricing: { day_price_cents: 500, vat_rate_percent: '24.00' },
  promotions: [],
};

function route(requests: unknown[], pending?: number, validate: (path: string) => unknown = () => valid()) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/admin/promotion-requests')) return queue(requests, pending);
    if (path.includes('/promotion-context')) return context;
    if (path.includes('/promotions/validate')) return validate(path);
    if (path.startsWith('/admin/promotions/cap-strip')) return { today: '2026-10-18', cap: 5, days: [] };
    throw new Error(`unexpected ${path}`);
  });
}

function valid(days = 7) {
  return { valid: true, errors: [], days, price: { net_cents: days * 500, vat_cents: days * 120, gross_cents: days * 620 } };
}

function renderQueue(initial = '/admin/promotions') {
  return renderWithProviders(
    <>
      <PromotionRequests />
      <LocationProbe />
    </>,
    { route: initial },
  );
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('PromotionRequests', () => {
  it('lists pending requests with the count, restriction tags and not-grantable reasons', async () => {
    route([
      request(),
      request({ id: 42, event_title: 'Craft Beer Weekend', promotion_restriction: 'alcohol', note: null }),
      request({
        id: 43,
        event_title: 'Telliskivi Makers Market',
        promotion_restriction: 'none',
        not_eligible_reason: 'organizer_not_owner',
        note: null,
      }),
      request({ id: 44, event_title: 'Kino Sõprus', promotion_restriction: null, not_eligible_reason: 'starts_too_early', note: null }),
    ]);
    renderQueue();
    expect(await screen.findByText('4 pending')).toBeInTheDocument();
    const beer = screen.getByText('Craft Beer Weekend').closest('li') as HTMLElement;
    expect(within(beer).getByText('Alcohol')).toBeInTheDocument();
    const jazz = screen.getByText('Tallinn Jazz Night').closest('li') as HTMLElement;
    expect(within(jazz).getByText('€35.00 + €8.40 VAT', { exact: false })).toBeInTheDocument();
    expect(within(jazz).getByText(/Could the Promotion start a day earlier/)).toBeInTheDocument();
    const dormant = screen.getByText('Telliskivi Makers Market').closest('li') as HTMLElement;
    expect(within(dormant).getByText(/Your claim is inactive/)).toBeInTheDocument();
    expect(within(dormant).getByText(/Stays pending until the claim is active again/)).toBeInTheDocument();
    const stale = screen.getByText('Kino Sõprus').closest('li') as HTMLElement;
    expect(within(stale).getByText('Not assessed')).toBeInTheDocument();
    expect(within(stale).getByText(/Edit the dates in the grant form/)).toBeInTheDocument();
  });

  it('opens the grant form prefilled from the request and posts the edited grant to the request endpoint', async () => {
    route([request()]);
    mockPost.mockResolvedValue({ id: 5 });
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: 'Grant Tallinn Jazz Night' }));
    expect(await screen.findByRole('heading', { name: 'Grant Promotion from request #41' })).toBeInTheDocument();
    expect(await screen.findByLabelText('Start date')).toHaveValue('2026-10-24');
    expect(screen.getByLabelText('End date')).toHaveValue('2026-10-30');
    expect(screen.getByLabelText('Advertiser legal name')).toHaveValue('Example Jazz Club MTÜ');
    expect(screen.getByLabelText('Registry code')).toHaveValue('80123456');
    expect(screen.getByLabelText('Billing email')).toHaveValue('info@jazzclub.example');
    expect(await screen.findByText('Dates match the request.')).toBeInTheDocument();

    const end = screen.getByLabelText('End date');
    await userEvent.clear(end);
    await userEvent.type(end, '2026-10-28');
    await userEvent.tab();
    expect(await screen.findByText(/Dates differ from the request/)).toBeInTheDocument();

    const submit = screen.getByRole('button', { name: 'Grant Promotion' });
    await waitFor(() => expect(submit).toBeEnabled());
    await userEvent.click(submit);
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    expect(mockPost).toHaveBeenCalledWith(
      '/admin/promotion-requests/41/grant',
      expect.objectContaining({
        start_date: '2026-10-24',
        end_date: '2026-10-28',
        advertiser_legal_name: 'Example Jazz Club MTÜ',
        advertiser_registry_code: '80123456',
        is_complimentary: false,
      }),
    );
    expect(await screen.findByText(/The request is marked granted\. The Organizer was not emailed/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Grant Promotion from request/ })).toBeNull();
  });

  it('asks for a restriction clearance before a restricted request can be granted', async () => {
    route([request({ id: 42, event_title: 'Craft Beer Weekend', promotion_restriction: 'alcohol' })]);
    mockPost.mockResolvedValue({ id: 6 });
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: 'Grant Craft Beer Weekend' }));
    expect(await screen.findByText('This event carries the alcohol restriction')).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Grant Promotion' });
    await waitFor(() => expect(screen.getByText('Dates are available.')).toBeInTheDocument());
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I reviewed this event/));
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Clearance note (required)'), 'Licensed venue, 18+ door check.');
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        '/admin/promotion-requests/42/grant',
        expect.objectContaining({
          restriction_clearance_confirmed: true,
          restriction_clearance_note: 'Licensed venue, 18+ door check.',
        }),
      ),
    );
  });

  it('declines through the shared Modal and refuses an empty reason', async () => {
    route([request()]);
    mockPost.mockResolvedValue({ id: 41, status: 'declined' });
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: 'Decline Tallinn Jazz Night' }));
    const dialog = await screen.findByRole('dialog', { name: 'Decline request for Tallinn Jazz Night' });
    expect(within(dialog).getByText(/emailed to info@jazzclub\.example/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Decline request' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Give a reason. It is emailed to the Organizer.');
    expect(mockPost).not.toHaveBeenCalled();

    await userEvent.type(within(dialog).getByLabelText(/Reason \(required/), '   ');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Decline request' }));
    expect(mockPost).not.toHaveBeenCalled();

    await userEvent.type(within(dialog).getByLabelText(/Reason \(required/), 'Add ticket information first.');
    expect(within(dialog).getByText('Add ticket information first.'.length + 3 + ' / 1000')).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Decline request' }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/admin/promotion-requests/41/decline', { reason: 'Add ticket information first.' }),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(await screen.findByText(/Declined Tallinn Jazz Night\. The reason is queued as an email/)).toBeInTheDocument();
  });

  it('shows the server refusal inside the decline dialog when another admin resolved the request', async () => {
    route([request()]);
    mockPost.mockRejectedValue(new ApiError(409, 'The request is no longer pending.'));
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: 'Decline Tallinn Jazz Night' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText(/Reason \(required/), 'No.');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Decline request' }));
    expect(await within(dialog).findByText('The request is no longer pending.')).toBeInTheDocument();
  });

  it('collapses to a quiet header with nothing pending and opens history through the URL', async () => {
    route([], 0);
    renderQueue();
    expect(await screen.findByText('0 pending')).toBeInTheDocument();
    expect(screen.queryByText('No pending requests')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Show history' }));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('?requests=granted');
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('status=granted')));
    expect(await screen.findByText('Nothing here')).toBeInTheDocument();
  });

  it('shows the reason sent on declined requests in history', async () => {
    route([request({ status: 'declined', decline_reason: 'Add ticket information first.', resolved_at: '2026-10-06T10:00:00+03:00', not_eligible_reason: null })]);
    renderQueue('/admin/promotions?requests=declined');
    expect(await screen.findByText(/Reason sent: Add ticket information first\./)).toBeInTheDocument();
    expect(screen.getByText('declined 6 Oct')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Grant Tallinn Jazz Night' })).toBeNull();
  });
});
