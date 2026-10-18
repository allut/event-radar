import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminPromotions from './AdminPromotions';
import { LocationProbe, renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);

function capDays() {
  return Array.from({ length: 14 }, (_, i) => {
    const day = String(17 + i).padStart(2, '0');
    const reserved = i === 7 ? 5 : i === 0 ? 2 : 0;
    return {
      date: `2026-10-${day}`,
      reserved,
      paid: reserved,
      unpaid: 0,
      live: i === 0 ? 2 : 0,
      cap: 5,
      free: 5 - reserved,
    };
  });
}

function promotion(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    event_id: 7,
    event_title: 'Noblessner Food Fest',
    organizer_name: 'Noblessner Events OÜ',
    status: 'paid',
    state: 'live',
    start_date: '2026-10-15',
    end_date: '2026-10-21',
    days: 7,
    net_price_cents: 3500,
    vat_rate_percent: '24.00',
    vat_cents: 840,
    gross_price_cents: 4340,
    is_complimentary: false,
    complimentary_note: null,
    invoice_reference: null,
    advertiser_legal_name: 'Noblessner Events OÜ',
    ...overrides,
  };
}

function listResponse(promotions: unknown[]) {
  return { today: '2026-10-17', promotions, total: promotions.length, limit: 50, offset: 0, has_more: false };
}

function routeGets(promotions: unknown[]) {
  mockGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/admin/promotions/cap-strip')) return { today: '2026-10-17', cap: 5, days: capDays() };
    if (path.startsWith('/admin/promotions')) return listResponse(promotions);
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => {
  mockGet.mockReset();
});

describe('AdminPromotions', () => {
  it('renders the cap strip with reserved counts out of the cap and marks full days', async () => {
    routeGets([]);
    renderWithProviders(<AdminPromotions />);
    expect(await screen.findByText('2/5')).toBeInTheDocument();
    const full = screen.getByText('5/5');
    expect(full.closest('[data-full="true"]')).not.toBeNull();
  });

  it('lists promotions with computed state pills and the unpaid reason', async () => {
    routeGets([
      promotion(),
      promotion({ id: 2, event_title: 'Telliskivi Makers Market', status: 'unpaid', state: 'scheduled', start_date: '2026-10-24', end_date: '2026-11-02' }),
      promotion({ id: 3, event_title: 'Kino Sõprus', is_complimentary: true, net_price_cents: 0, state: 'finished', status: 'ended_early' }),
    ]);
    renderWithProviders(<AdminPromotions />);
    const live = (await screen.findByText('Noblessner Food Fest')).closest('tr') as HTMLElement;
    expect(within(live).getByText('Live')).toBeInTheDocument();
    expect(within(live).getByText('€35.00 + VAT')).toBeInTheDocument();
    const unpaid = screen.getByText('Telliskivi Makers Market').closest('tr') as HTMLElement;
    expect(within(unpaid).getByText('Awaiting payment')).toBeInTheDocument();
    expect(within(unpaid).getByText(/voids when Sat 24 Oct begins/)).toBeInTheDocument();
    expect(within(unpaid).getByText('24 Oct – 2 Nov')).toBeInTheDocument();
    const ended = screen.getByText('Kino Sõprus').closest('tr') as HTMLElement;
    expect(within(ended).getByText('Ended early')).toBeInTheDocument();
    expect(within(ended).getByText('Complimentary')).toBeInTheDocument();
  });

  it('links each row to its Promotion detail', async () => {
    routeGets([promotion({ id: 12 })]);
    renderWithProviders(<AdminPromotions />);
    const link = await screen.findByRole('link', { name: 'Manage' });
    expect(link).toHaveAttribute('href', '/admin/promotions/12');
  });

  it('filters by state through the URL and the request', async () => {
    routeGets([]);
    renderWithProviders(
      <>
        <AdminPromotions />
        <LocationProbe />
      </>,
    );
    await screen.findByText('No Promotions');
    await userEvent.click(screen.getByRole('tab', { name: 'Live' }));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('?state=live');
    await vi.waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/admin/promotions?state=live&limit=50&offset=0')),
    );
  });
});
