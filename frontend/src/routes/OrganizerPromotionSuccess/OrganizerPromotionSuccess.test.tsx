import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerPromotionSuccess from './OrganizerPromotionSuccess';
import { renderWithProviders } from '../../test/utils';
import type { OrganizerPromotionItem } from '../../lib/organizerPromotions';

vi.mock('../../hooks/useOrganizerLogout', () => ({ useOrganizerLogout: () => vi.fn() }));
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);

function promotion(status: OrganizerPromotionItem['status']): OrganizerPromotionItem {
  return {
    kind: 'promotion',
    id: 9,
    event_id: 5,
    event_title: 'Kalamaja Open Doors',
    status,
    paused_reason: null,
    decline_reason: null,
    note: null,
    start_date: '2026-10-29',
    end_date: '2026-11-03',
    days: 6,
    advertiser_legal_name: 'Example Community MTÜ',
    advertiser_registry_code: '12345678',
    billing_email: null,
    price: { net_cents: 3000, vat_cents: 720, gross_cents: 3720 },
    can_withdraw: false,
    has_report: true,
    created_at: '2026-10-18T10:00:00+03:00',
  };
}

function renderPage(route = '/en/organizer/promotions/checkout/success?promotion_id=9') {
  return renderWithProviders(<OrganizerPromotionSuccess />, {
    route,
    pathPattern: '/:locale/organizer/promotions/checkout/success',
  });
}

beforeEach(() => {
  mockGet.mockReset();
  localStorage.clear();
});

describe('OrganizerPromotionSuccess (#618)', () => {
  it('confirms the payment with a recap once the Promotion is paid', async () => {
    mockGet.mockResolvedValue({ items: [promotion('scheduled')] });
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Payment received' }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/Your Promotion is scheduled\. It starts on Thu 29 Oct, and the VAT invoice is on its way to your inbox\./)).toBeInTheDocument();
    const status = screen.getByRole('status');
    expect(within(status).getByText('Kalamaja Open Doors')).toBeInTheDocument();
    expect(within(status).getByText('29 Oct – 3 Nov · 6 days')).toBeInTheDocument();
    expect(within(status).getByText('€37.20')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View your Promotions' })).toHaveAttribute('href', '/en/organizer/promotions');
  });

  it('does not claim success while the webhook has not landed (still awaiting payment)', async () => {
    mockGet.mockResolvedValue({ items: [promotion('awaiting_payment')] });
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Confirming your payment…' })).toBeInTheDocument();
    expect(screen.getByText(/This usually takes a few seconds\./)).toBeInTheDocument();
    expect(screen.getByText(/we refund it in full automatically and email you\./)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Payment received' })).not.toBeInTheDocument();
  });

  it('flips to the confirmation when Check again finds the paid Promotion', async () => {
    mockGet.mockResolvedValueOnce({ items: [promotion('awaiting_payment')] });
    renderPage();
    await screen.findByRole('heading', { name: 'Confirming your payment…' });

    mockGet.mockResolvedValue({ items: [promotion('live')] });
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Payment received' })).toBeInTheDocument());
  });

  it('keeps asking until the payment is confirmed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockGet.mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [promotion('scheduled')] });
      renderPage();
      await screen.findByRole('heading', { name: 'Confirming your payment…' });

      await vi.advanceTimersByTimeAsync(3100);

      await waitFor(() => expect(screen.getByRole('heading', { name: 'Payment received' })).toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });
});
