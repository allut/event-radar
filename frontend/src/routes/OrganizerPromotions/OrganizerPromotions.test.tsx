import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerPromotions from './OrganizerPromotions';
import { LocationProbe, renderWithProviders } from '../../test/utils';
import type { OrganizerPromotionItem, PromotionReport } from '../../lib/organizerPromotions';

vi.mock('../../hooks/useOrganizerLogout', () => ({ useOrganizerLogout: () => vi.fn() }));
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn() },
}));

import { ApiError, organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

function item(overrides: Partial<OrganizerPromotionItem>): OrganizerPromotionItem {
  return {
    kind: 'promotion',
    id: 1,
    event_id: 10,
    event_title: 'Telliskivi Makers Market',
    status: 'scheduled',
    paused_reason: null,
    decline_reason: null,
    note: null,
    start_date: '2026-10-24',
    end_date: '2026-10-27',
    days: 4,
    advertiser_legal_name: 'Example Makers OÜ',
    advertiser_registry_code: '12345678',
    billing_email: null,
    price: { net_cents: 2000, vat_cents: 480, gross_cents: 2480 },
    can_withdraw: false,
    has_report: true,
    created_at: '2026-10-10T10:00:00+03:00',
    ...overrides,
  };
}

const ALL_STATUSES: OrganizerPromotionItem[] = [
  item({ kind: 'request', id: 3, status: 'requested', can_withdraw: true, has_report: false, event_title: 'Requested Show' }),
  item({ kind: 'request', id: 4, status: 'declined', decline_reason: 'The event page does not name an organiser.', has_report: false, event_title: 'Declined Show' }),
  item({ id: 5, status: 'awaiting_payment', event_title: 'Awaiting Show' }),
  item({ id: 6, status: 'scheduled', event_title: 'Scheduled Show' }),
  item({ id: 7, status: 'live', end_date: '2026-10-20', event_title: 'Live Show' }),
  item({ id: 8, status: 'paused', paused_reason: 'organizer_not_owner', event_title: 'Paused Show' }),
  item({ id: 9, status: 'finished', event_title: 'Finished Show' }),
  item({ id: 11, status: 'ended_early', event_title: 'Ended Show' }),
  item({ id: 12, status: 'cancelled', has_report: false, event_title: 'Cancelled Show' }),
];

function serve(items: OrganizerPromotionItem[], report?: PromotionReport) {
  mockGet.mockImplementation(async (path: string) => {
    if (path === '/organizer/promotions') return { items };
    if (path.endsWith('/report') && report) return report;
    throw new ApiError(404, 'Not Found');
  });
}

function renderPage(route = '/en/organizer/promotions') {
  const page = (
    <>
      <OrganizerPromotions />
      <LocationProbe />
    </>
  );
  return renderWithProviders(null, {
    route,
    routes: [
      { path: '/:locale/organizer/promotions', element: page },
      { path: '/:locale/organizer/dashboard', element: <LocationProbe /> },
    ],
  });
}

const rowFor = (title: string) => screen.getByText(title).closest('li') as HTMLElement;

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  localStorage.clear();
});

describe('OrganizerPromotions (#614)', () => {
  it('explains what a Promotion is with the per-day price and VAT', async () => {
    serve([]);
    renderPage();

    expect(await screen.findByRole('heading', { level: 1, name: 'Promotions' })).toBeInTheDocument();
    expect(screen.getByText('€5/day + VAT (€6.20)')).toBeInTheDocument();
    expect(screen.getByText(/separate card marked “Ad”/)).toBeInTheDocument();
    expect(screen.getByText('Your event’s normal position in Explore and Daily 5 doesn’t change.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Hide' }));
    expect(screen.queryByText('€5/day + VAT (€6.20)')).not.toBeInTheDocument();
  });

  it('words the price in Estonian with a decimal comma', async () => {
    serve([]);
    renderPage('/et/organizer/promotions');

    expect(await screen.findByText('€5/päev + käibemaks (€6,20)')).toBeInTheDocument();
  });

  it('lists every status with its badge and a plain-words reason', async () => {
    serve(ALL_STATUSES);
    renderPage();
    await screen.findByText('Requested Show');

    const expected: Array<[string, string, RegExp]> = [
      ['Requested Show', 'Requested', /Waiting for review/],
      ['Declined Show', 'Declined', /Reason: The event page does not name an organiser\./],
      ['Awaiting Show', 'Awaiting payment', /Your days stay held until it’s paid/],
      ['Scheduled Show', 'Scheduled', /Starts Sat 24 Oct\./],
      ['Live Show', 'Live', /Showing now\. Runs until Tue 20 Oct\./],
      ['Paused Show', 'Paused', /Paused today because your claim on this event is inactive\./],
      ['Finished Show', 'Finished', /Ran 24–27 Oct\./],
      ['Ended Show', 'Ended early', /Ended before its last day/],
      ['Cancelled Show', 'Cancelled', /Cancelled\. It won’t run\./],
    ];
    for (const [title, badge, reason] of expected) {
      const row = within(rowFor(title));
      expect(row.getByText(badge)).toBeInTheDocument();
      expect(row.getByText(reason)).toBeInTheDocument();
    }
    expect(within(rowFor('Scheduled Show')).getByText(/24–27 Oct · 4 days · Example Makers OÜ/)).toBeInTheDocument();
  });

  it('names the billing email in the awaiting-payment text, and the card hold has no invoice wording', async () => {
    serve([
      item({ id: 21, status: 'awaiting_payment', event_title: 'Emailed Show', billing_email: 'pay@acme.example' }),
      item({ id: 22, status: 'awaiting_checkout', event_title: 'Checkout Show', billing_email: 'pay@acme.example' }),
    ]);
    renderPage();
    await screen.findByText('Emailed Show');

    const emailed = within(rowFor('Emailed Show'));
    expect(emailed.getByText(/We emailed an invoice to pay@acme\.example\./)).toBeInTheDocument();
    const checkout = within(rowFor('Checkout Show'));
    expect(checkout.getByText('Awaiting checkout')).toBeInTheDocument();
    expect(checkout.getByText(/Card checkout started/)).toBeInTheDocument();
    expect(checkout.queryByText(/invoice/i)).not.toBeInTheDocument();
  });

  it('words a paused reason in the viewer’s language and falls back for an unknown code', async () => {
    serve([
      item({ id: 8, status: 'paused', paused_reason: 'event_not_public', event_title: 'Paused Show' }),
      item({ id: 9, status: 'paused', paused_reason: 'some_new_gate', event_title: 'Other Show' }),
    ]);
    renderPage('/ru/organizer/promotions');

    expect(
      await within(await screen.findByText('Paused Show').then((n) => n.closest('li') as HTMLElement)).findByText(
        /Сегодня приостановлено, потому что страница события была снята с публикации\./,
      ),
    ).toBeInTheDocument();
    expect(within(rowFor('Other Show')).getByText(/одна из проверок перед показом не пройдена/)).toBeInTheDocument();
  });

  it('shows the empty state with a way back to Your events', async () => {
    serve([]);
    renderPage();

    expect(await screen.findByText('No Promotions yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to Your events' })).toHaveAttribute('href', '/en/organizer/dashboard');
  });

  it('sends the Organizer back to Your events when the offer is off (the list 404s)', async () => {
    mockGet.mockRejectedValue(new ApiError(404, 'Not Found'));
    renderPage();

    await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/organizer/dashboard'));
  });

  describe('withdraw', () => {
    it('offers Withdraw only on a pending request, asks to confirm, then withdraws and refreshes', async () => {
      serve(ALL_STATUSES);
      mockPost.mockResolvedValue({});
      renderPage();
      await screen.findByText('Requested Show');

      expect(screen.getAllByRole('button', { name: 'Withdraw' })).toHaveLength(1);
      await userEvent.click(within(rowFor('Requested Show')).getByRole('button', { name: 'Withdraw' }));
      const dialog = screen.getByRole('alertdialog', { name: 'Withdraw this request?' });
      await userEvent.click(within(dialog).getByRole('button', { name: 'Withdraw request' }));

      await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/organizer/promotions/requests/3/withdraw'));
      await waitFor(() => expect(mockGet.mock.calls.filter(([p]) => p === '/organizer/promotions').length).toBeGreaterThan(1));
    });

    it('keeps the request when the Organizer chooses Keep it', async () => {
      serve(ALL_STATUSES);
      renderPage();
      await screen.findByText('Requested Show');

      await userEvent.click(within(rowFor('Requested Show')).getByRole('button', { name: 'Withdraw' }));
      await userEvent.click(screen.getByRole('button', { name: 'Keep it' }));

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(mockPost).not.toHaveBeenCalled();
    });
  });

  describe('invoice link', () => {
    it('links the hosted invoice on a card-paid row only', async () => {
      serve([
        item({ id: 1, status: 'scheduled', event_title: 'Paid Show', invoice_url: 'https://invoice.stripe.com/i/abc' }),
        item({ id: 2, status: 'scheduled', event_title: 'Invoiced Show', invoice_url: null }),
      ]);
      renderPage();
      await screen.findByText('Paid Show');

      const link = within(rowFor('Paid Show')).getByRole('link', { name: 'Open the invoice for Paid Show' });
      expect(link).toHaveAttribute('href', 'https://invoice.stripe.com/i/abc');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      expect(within(rowFor('Invoiced Show')).queryByRole('link', { name: /invoice/i })).not.toBeInTheDocument();
    });
  });

  describe('per-day report (#616)', () => {
    const report: PromotionReport = {
      promotion_id: 7,
      event_id: 10,
      start_date: '2026-10-14',
      end_date: '2026-10-20',
      updated: 'daily',
      through: '2026-10-16',
      daily5_reach: 214,
      days: [
        { day: '2026-10-14', shown: true, paused: false, paused_reason: null, explore_served: 312, daily5_placed: 80, digest_sent: 41, web_opens: 9, digest_opens: 4 },
        { day: '2026-10-15', shown: false, paused: true, paused_reason: 'event_not_public', explore_served: 0, daily5_placed: 0, digest_sent: 0, web_opens: 0, digest_opens: 0 },
      ],
    };

    it('offers the report only on a Promotion that has run, and expands it on demand', async () => {
      serve(ALL_STATUSES, report);
      renderPage();
      await screen.findByText('Live Show');

      // live, paused, finished and ended early have days to report on.
      expect(screen.getAllByRole('button', { name: /Daily report/ })).toHaveLength(4);
      expect(within(rowFor('Scheduled Show')).queryByRole('button', { name: /Daily report/ })).not.toBeInTheDocument();
      expect(mockGet).not.toHaveBeenCalledWith('/organizer/promotions/7/report');

      const toggle = within(rowFor('Live Show')).getByRole('button', { name: /Daily report/ });
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'true');
      await screen.findByRole('table');
      expect(mockGet).toHaveBeenCalledWith('/organizer/promotions/7/report');
    });

    it('tabulates complete days: shown figures, a paused day in plain words, and no viewer data', async () => {
      serve([item({ id: 7, status: 'live', event_title: 'Live Show' })], report);
      renderPage();
      await userEvent.click(await screen.findByRole('button', { name: /Daily report/ }));

      const table = await screen.findByRole('table');
      expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
        'Day',
        'Status',
        'Explore shown',
        'Daily 5 placed',
        'Digest sent',
        'Opens',
      ]);
      const [shown, paused] = within(table).getAllByRole('row').slice(1);
      expect(within(shown).getAllByRole('cell').map((c) => c.textContent)).toEqual([
        'Wed 14 Oct',
        'Shown',
        '312',
        '80',
        '41',
        '13', // web opens + digest opens
      ]);
      expect(within(paused).getAllByRole('cell').map((c) => c.textContent)).toEqual([
        'Thu 15 Oct',
        'Paused: event unpublished',
        '—',
        '—',
        '—',
        '—',
      ]);
      const panel = screen.getByRole('region', { name: 'Daily report for Live Show' });
      expect(within(panel).getByText('Updated daily · complete days only')).toBeInTheDocument();
    });

    it('shows one Daily 5 reach figure (still growing while live) and the honest notes', async () => {
      serve([item({ id: 7, status: 'live', event_title: 'Live Show' })], report);
      renderPage();
      await userEvent.click(await screen.findByRole('button', { name: /Daily report/ }));

      const panel = await screen.findByRole('region', { name: 'Daily report for Live Show' });
      await within(panel).findByRole('table');
      expect(within(panel).getByText('Daily 5 reach · so far')).toBeInTheDocument();
      expect(within(panel).getByText('214 people')).toBeInTheDocument();
      expect(within(panel).getByText(/doesn’t mean anyone saw it/)).toBeInTheDocument();
      expect(within(panel).getByText('Known bots are excluded.')).toBeInTheDocument();
      expect(within(panel).getByText(/Nothing is guaranteed/)).toBeInTheDocument();
    });

    it('says so when no complete day exists yet, and when the report cannot load', async () => {
      serve([item({ id: 7, status: 'live', event_title: 'Live Show' })], { ...report, days: [], daily5_reach: null });
      renderPage();
      await userEvent.click(await screen.findByRole('button', { name: /Daily report/ }));
      expect(await screen.findByText('No complete days yet. The first day appears tomorrow.')).toBeInTheDocument();
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('shows an error line when the report request fails', async () => {
      serve([item({ id: 7, status: 'finished', event_title: 'Done Show' })]);
      renderPage();
      await userEvent.click(await screen.findByRole('button', { name: /Daily report/ }));
      expect(await screen.findByText('Couldn’t load the daily report.')).toBeInTheDocument();
    });
  });

  it('scrolls to and focuses the event’s open item when arriving from a row badge', async () => {
    const scroll = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scroll;
    serve([
      item({ id: 1, event_id: 10, status: 'finished', event_title: 'Old Run' }),
      item({ id: 2, event_id: 10, status: 'live', event_title: 'Current Run' }),
      item({ id: 3, event_id: 11, status: 'live', event_title: 'Other Event' }),
    ]);
    renderPage('/en/organizer/promotions?event=10');

    await screen.findByText('Current Run');
    await waitFor(() => expect(rowFor('Current Run')).toHaveFocus());
    expect(scroll).toHaveBeenCalled();
  });
});
