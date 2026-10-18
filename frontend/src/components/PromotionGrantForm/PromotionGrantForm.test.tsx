import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromotionGrantForm from './PromotionGrantForm';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

function context(overrides: Record<string, unknown> = {}) {
  return {
    event_id: 42,
    event_title: 'Tallinn Jazz Night',
    owner: { organizer_id: 9, name: 'Jazzklubi MTÜ', email: 'info@jazzklubi.ee' },
    prefill: { advertiser_legal_name: 'Jazzklubi MTÜ', billing_email: 'info@jazzklubi.ee' },
    today: '2026-10-17',
    earliest_start: '2026-10-18',
    event_last_day: '2026-10-30',
    rules: { min_days: 3, max_days: 14, cap: 5, cap_strip_days: 14 },
    pricing: { day_price_cents: 500, vat_rate_percent: '24.00' },
    promotions: [],
    ...overrides,
  };
}

const capStrip = {
  today: '2026-10-17',
  cap: 5,
  days: Array.from({ length: 14 }, (_, i) => ({
    date: `2026-10-${String(17 + i).padStart(2, '0')}`,
    reserved: 0,
    paid: 0,
    unpaid: 0,
    live: 0,
    cap: 5,
    free: 5,
  })),
};

function validation(overrides: Record<string, unknown> = {}) {
  return {
    valid: true,
    errors: [],
    days: 7,
    price: { net_cents: 3500, vat_cents: 840, gross_cents: 4340 },
    ...overrides,
  };
}

function setup(ctx: unknown = context(), validate: (path: string) => unknown = () => validation()) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.includes('/promotion-context')) return ctx;
    if (path.includes('/promotions/validate')) return validate(path);
    if (path.startsWith('/admin/promotions/cap-strip')) return capStrip;
    throw new Error(`unexpected ${path}`);
  });
  const onNotify = vi.fn();
  renderWithProviders(<PromotionGrantForm eventId="42" onNotify={onNotify} />);
  return { onNotify };
}

async function pickDates(start = '2026-10-20', end = '2026-10-26') {
  const startInput = await screen.findByLabelText('Start date');
  fireEvent.change(startInput, { target: { value: start } });
  fireEvent.change(screen.getByLabelText('End date'), { target: { value: end } });
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('PromotionGrantForm', () => {
  it('explains why an unowned event cannot be promoted and renders no form', async () => {
    setup(context({ owner: null, prefill: { advertiser_legal_name: null, billing_email: null } }));
    expect(await screen.findByText(/no owning Organizer/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Start date')).toBeNull();
  });

  it('prefills the advertiser from the owner and shows the live price for valid dates', async () => {
    setup();
    await pickDates();
    expect(screen.getByLabelText('Advertiser legal name')).toHaveValue('Jazzklubi MTÜ');
    expect(screen.getByLabelText('Billing email')).toHaveValue('info@jazzklubi.ee');
    expect(await screen.findByText('Dates are available.')).toBeInTheDocument();
    expect(screen.getByText('€35.00 + €8.40 VAT = €43.40')).toBeInTheDocument();
    expect(screen.getByText('7 days × €5.00 net · VAT 24%')).toBeInTheDocument();
  });

  it('shows the server rule message and blocks submit when the window breaks a rule', async () => {
    setup(context(), () =>
      validation({
        valid: false,
        errors: [{ code: 'cap_exceeded', message: 'More than 5 Promotions would be live on a day in this window.', dates: ['2026-10-24'] }],
      }),
    );
    await pickDates();
    expect(await screen.findByText(/More than 5 Promotions/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeDisabled();
  });

  it('requires a registry code of 8 digits', async () => {
    setup();
    await pickDates();
    await screen.findByText('Dates are available.');
    await userEvent.type(screen.getByLabelText('Registry code'), '123');
    expect(screen.getByText('Registry code must be 8 digits.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeDisabled();
  });

  it('reveals a required note for a complimentary grant and shows the free price', async () => {
    setup();
    await pickDates();
    await userEvent.type(screen.getByLabelText('Registry code'), '80123456');
    await userEvent.click(screen.getByLabelText('Complimentary (€0)'));
    expect(await screen.findByText('Complimentary grants need a note.')).toBeInTheDocument();
    expect(screen.getByText('Complimentary · €0.00')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Note (required)'), 'Pilot partner');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeEnabled());
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('is_complimentary=true'));
  });

  it('posts the grant and notifies on success', async () => {
    mockPost.mockResolvedValue({ id: 5 });
    const { onNotify } = setup();
    await pickDates();
    await userEvent.type(screen.getByLabelText('Registry code'), '80123456');
    await userEvent.type(screen.getByLabelText('Invoice reference'), 'ER-M-0001');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Grant Promotion' }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/admin/events/42/promotions', {
        start_date: '2026-10-20',
        end_date: '2026-10-26',
        advertiser_legal_name: 'Jazzklubi MTÜ',
        advertiser_registry_code: '80123456',
        billing_email: 'info@jazzklubi.ee',
        is_complimentary: false,
        complimentary_note: null,
        invoice_reference: 'ER-M-0001',
      }),
    );
    await waitFor(() => expect(onNotify).toHaveBeenCalledWith('success', 'Promotion granted.'));
  });

  it('reports a refused grant through onNotify', async () => {
    mockPost.mockRejectedValue(new ApiError(409, 'The window overlaps another Promotion on this event.'));
    const { onNotify } = setup();
    await pickDates();
    await userEvent.type(screen.getByLabelText('Registry code'), '80123456');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Grant Promotion' }));
    await waitFor(() =>
      expect(onNotify).toHaveBeenCalledWith('error', 'The window overlaps another Promotion on this event.'),
    );
  });
});
