import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerPromotionRequest from './OrganizerPromotionRequest';
import { makeEvent, renderWithProviders } from '../../test/utils';
import type { PromotionRequestContext } from '../../lib/organizerPromotions';

vi.mock('../../hooks/useOrganizerLogout', () => ({ useOrganizerLogout: () => vi.fn() }));
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { get: vi.fn() },
  organizerApi: { get: vi.fn(), post: vi.fn() },
}));

import { ApiError, api, organizerApi } from '../../api/client';
const mockApiGet = vi.mocked(api.get);
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

const SOLD_OUT = '2026-10-27';
const VALID_CODE = '12345678'; // passes the check digit
const BAD_CODE = '12345679';

const context: PromotionRequestContext = {
  event_id: 5,
  event_title: 'Kalamaja Open Doors',
  promotable: true,
  badge: null,
  checkout_available: true,
  review_required: false,
  today: '2026-10-18',
  earliest_start: '2026-10-19',
  event_last_day: '2026-11-08',
  rules: { min_days: 3, max_days: 14 },
  pricing: { day_price_cents: 500, vat_rate_percent: '24.00' },
  terms_version: 1,
  billing_email_default: 'mari@kalamaja.example',
  unavailable_dates: [SOLD_OUT, '2026-10-28'],
};

function priceFor(days: number) {
  const net = days * 500;
  const vat = Math.round(net * 0.24);
  return { net_cents: net, vat_cents: vat, gross_cents: net + vat };
}

/** A tiny stand-in for GET /validate: length, sold-out days and the event's end. */
function validate(start: string, end: string) {
  const days = Math.round((Date.parse(end) - Date.parse(start)) / 864e5) + 1;
  const errors: Array<{ code: string; message: string; dates: string[] }> = [];
  if (days < 3) errors.push({ code: 'window_too_short', message: 'x', dates: [] });
  else if (days > 14) errors.push({ code: 'window_too_long', message: 'x', dates: [] });
  if (end > context.event_last_day) errors.push({ code: 'ends_after_event', message: 'x', dates: [] });
  if (start <= SOLD_OUT && end >= SOLD_OUT) errors.push({ code: 'cap_exceeded', message: 'x', dates: [SOLD_OUT] });
  return { valid: errors.length === 0, errors, days, price: priceFor(days) };
}

interface Setup {
  route?: string;
  ctx?: Partial<PromotionRequestContext>;
  lookup?: (code: string) => Promise<unknown>;
}

function setup({ route = '/en/organizer/promotions/new?event_id=5', ctx, lookup }: Setup = {}) {
  mockGet.mockImplementation(async (path: string) => {
    const url = new URL(path, 'http://x');
    if (url.pathname === '/organizer/promotions/context') return { ...context, ...ctx };
    if (url.pathname === '/organizer/promotions/validate') {
      return validate(url.searchParams.get('start_date')!, url.searchParams.get('end_date')!);
    }
    throw new ApiError(404, 'Not Found');
  });
  mockApiGet.mockResolvedValue(
    makeEvent({
      id: 5,
      title: 'Kalamaja Open Doors',
      venue_name: 'Kalamaja',
      starts_at: '2026-10-24T11:00:00+03:00',
      why_go: ['Studios and courtyards open to visitors'],
    }),
  );
  mockPost.mockImplementation(async (path: string, body?: unknown) => {
    if (path === '/organizer/promotions/registry-lookup') {
      const code = (body as { registry_code: string }).registry_code;
      return lookup ? lookup(code) : { registry_code: code, legal_name: 'Kalamaja Kogukond MTÜ' };
    }
    throw new Error(`unexpected POST ${path}`);
  });
  return renderWithProviders(<OrganizerPromotionRequest />, {
    route,
    pathPattern: '/:locale/organizer/promotions/new',
  });
}

const field = (name: string | RegExp) => screen.getByLabelText(name, { selector: 'input,textarea' });

async function typeDate(label: string, value: string) {
  const input = field(label);
  await userEvent.clear(input);
  await userEvent.type(input, value);
  await userEvent.tab();
}

async function fillDates(start = '2026-10-29', end = '2026-11-03') {
  await typeDate('Start date', start);
  await typeDate('End date', end);
}

async function fillBusiness() {
  await userEvent.type(field('Registry code'), VALID_CODE);
  await waitFor(() => expect(field('Legal name')).toHaveAttribute('readonly'));
}

/** The DatePicker cell for an ISO day (its data-date is a Date#toDateString). */
function calendarCell(container: HTMLElement, iso: string): HTMLElement {
  const [y, m, d] = iso.split('-').map(Number);
  return container.querySelector(`[data-date="${new Date(y, m - 1, d).toDateString()}"]`) as HTMLElement;
}

const assign = vi.fn();
beforeEach(() => {
  mockApiGet.mockReset();
  mockGet.mockReset();
  mockPost.mockReset();
  assign.mockReset();
  vi.stubGlobal('location', { assign, href: 'http://localhost/', origin: 'http://localhost' });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('OrganizerPromotionRequest (#614, #617, #618)', () => {
  it('fixes the event, and asks the server about this event only', async () => {
    setup();

    expect(await screen.findByRole('heading', { level: 1, name: 'Promote “Kalamaja Open Doors”' })).toBeInTheDocument();
    expect(screen.getByText('Fixed: you opened this from Your events')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/organizer/promotions/context?event_id=5');
  });

  it('says the event cannot be promoted when it is not promotable now', async () => {
    setup({ ctx: { promotable: false, badge: 'requested' } });

    expect(await screen.findByRole('heading', { name: 'This event can’t be promoted right now' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Start date')).not.toBeInTheDocument();
  });

  describe('price and VAT copy', () => {
    it('shows the per-day price with VAT before any date is picked', async () => {
      setup();

      expect(await screen.findByText('€5/day + VAT (€6.20)')).toBeInTheDocument();
      expect(screen.getByText('Choose your dates to see the total.')).toBeInTheDocument();
      expect(screen.getByText('Your event’s normal position in Explore and Daily 5 doesn’t change.')).toBeInTheDocument();
    });

    it('shows the total as net + VAT = total, and the same amount on the Pay button', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-29', '2026-11-03');

      expect(await screen.findByText('€30 + €7.20 VAT = €37.20')).toBeInTheDocument();
      expect(screen.getByText(/6 days · 29 Oct – 3 Nov/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Pay €37.20' })).toBeInTheDocument();
    });

    it('uses a decimal comma and the Estonian VAT word', async () => {
      setup({ route: '/et/organizer/promotions/new?event_id=5' });

      expect(await screen.findByText('€5/päev + käibemaks (€6,20)')).toBeInTheDocument();
    });
  });

  describe('live EventCard preview', () => {
    it('shows the real event with an Ad caption and a placeholder until the business is known', async () => {
      setup();

      const card = (await screen.findByText('Studios and courtyards open to visitors')).closest('article') as HTMLElement;
      expect(within(card).getByText('Ad')).toBeInTheDocument();
      expect(within(card).getByText(/Your business name/)).toBeInTheDocument();
      expect(within(card).getByRole('heading', { name: 'Kalamaja Open Doors' })).toBeInTheDocument();
      expect(within(card).getByRole('link', { name: 'Kalamaja Open Doors' })).toHaveAttribute('rel', 'sponsored');
    });

    it('updates the caption as the legal name is typed (registry down: free text)', async () => {
      setup({ lookup: async () => { throw new ApiError(503, 'x', 'registry_unavailable'); } });
      await screen.findByLabelText('Registry code');
      await userEvent.type(field('Registry code'), VALID_CODE);
      await userEvent.type(await screen.findByLabelText('Legal name'), 'Studio Nord OÜ');

      const card = screen.getByText('Studios and courtyards open to visitors').closest('article') as HTMLElement;
      expect(within(card).getByText(/Studio Nord OÜ/)).toBeInTheDocument();
    });

    it('takes the caption from the registry once the code is found', async () => {
      setup();
      await screen.findByLabelText('Registry code');
      await fillBusiness();

      const card = screen.getByText('Studios and courtyards open to visitors').closest('article') as HTMLElement;
      expect(within(card).getByText(/Kalamaja Kogukond MTÜ/)).toBeInTheDocument();
    });

    it('opens the Why? panel with the no-interests explanation', async () => {
      setup();
      await userEvent.click(await screen.findByRole('button', { name: 'Why?' }, { timeout: 8000 }));

      expect(screen.getByText(/never your interests\. The order of results is unchanged/)).toBeInTheDocument();
    });
  });

  describe('dates and sold-out days', () => {
    it('refuses a sold-out day typed into the field, and an end past the event', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await typeDate('Start date', SOLD_OUT);
      expect(field('Start date')).toHaveValue('');
      await typeDate('Start date', '2026-10-29');
      expect(field('Start date')).toHaveValue('2026-10-29');
      await typeDate('End date', '2026-11-09'); // event's last day is 2026-11-08
      expect(field('End date')).toHaveValue('');
      await typeDate('End date', '2026-10-28'); // before the start
      expect(field('End date')).toHaveValue('');
    });

    it('greys sold-out days and days before tomorrow in the calendar, and shows no counts', async () => {
      const { container } = setup();
      await screen.findByLabelText('Start date');
      await typeDate('Start date', '2026-10-29');
      await userEvent.click(screen.getAllByRole('button', { name: /open calendar/i })[0]);

      const cell = (day: string) => calendarCell(container, day);
      expect(cell(SOLD_OUT)).toBeDisabled();
      expect(cell(SOLD_OUT)).toHaveAttribute('aria-disabled', 'true');
      expect(cell('2026-10-28')).toBeDisabled();
      expect(cell('2026-10-18')).toBeDisabled(); // today: the earliest start is tomorrow
      expect(cell('2026-10-19')).not.toBeDisabled();
      expect(cell('2026-10-26')).not.toBeDisabled();
      expect(screen.getByRole('dialog')).not.toHaveTextContent(/booked|full|left|slots/i);
    });

    it('limits the end picker to the start and 14 days after it', async () => {
      const { container } = setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-20', '2026-10-25');
      await userEvent.click(screen.getAllByRole('button', { name: /open calendar/i })[1]);

      const cell = (day: string) => calendarCell(container, day);
      expect(cell('2026-10-19')).toBeDisabled(); // before the start
      expect(cell('2026-10-20')).not.toBeDisabled();
      await userEvent.click(screen.getByRole('button', { name: /next month/i }));
      expect(cell('2026-11-02')).not.toBeDisabled(); // 14th day
      expect(cell('2026-11-03')).toBeDisabled(); // 15th day
    });

    it('stops the end picker at the event’s last day', async () => {
      const { container } = setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-30', '2026-11-04');
      await userEvent.click(screen.getAllByRole('button', { name: /open calendar/i })[1]);

      const cell = (day: string) => calendarCell(container, day);
      expect(cell('2026-11-08')).not.toBeDisabled();
      expect(cell('2026-11-09')).toBeDisabled();
    });

    it('clears an end date that no longer fits when the start moves', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-29', '2026-11-03');
      await typeDate('Start date', '2026-11-05');
      expect(field('End date')).toHaveValue('');
    });

    it('words a too-short window live, from the server’s rule code', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-29', '2026-10-30');

      expect(await screen.findByText('A Promotion runs 3 to 14 days in a row. Yours is 2 days.')).toBeInTheDocument();
      expect(field('End date')).toHaveAttribute('aria-invalid', 'true');
    });

    it('names the sold-out day when a window spans one', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await typeDate('Start date', '2026-10-25');
      await typeDate('End date', '2026-10-30');

      expect(await screen.findByText(/Tue 27 Oct is fully booked\. Choose a window that avoids it\./)).toBeInTheDocument();
    });
  });

  describe('form validation', () => {
    it('lists what is missing and sends nothing when the form is submitted empty', async () => {
      setup();
      await screen.findByLabelText('Start date');

      await userEvent.click(screen.getByRole('button', { name: /^Pay [€…]/ }));

      expect(await screen.findAllByText(/Choose a start and an end date\./)).not.toHaveLength(0);
      expect(screen.getByText(/Fix the highlighted fields to continue\. Choose a start and an end date\./)).toBeInTheDocument();
      expect(mockPost).not.toHaveBeenCalled();
    });

    it('asks for the terms, and for the content policy on the card path only', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await fillDates();
      await fillBusiness();

      await userEvent.click(screen.getByRole('button', { name: /^Pay [€…]/ }));
      expect(await screen.findByText(/Accept the Organizer terms to continue\./)).toBeInTheDocument();

      await userEvent.click(screen.getByRole('checkbox', { name: /I accept the Organizer terms/ }));
      await userEvent.click(screen.getByRole('button', { name: /^Pay [€…]/ }));
      expect(await screen.findByText(/Confirm the content policy to continue\./)).toBeInTheDocument();
      expect(mockPost).not.toHaveBeenCalledWith('/organizer/promotions/checkout', expect.anything());

      await userEvent.click(screen.getByRole('button', { name: 'Pay by bank transfer instead' }));
      expect(screen.queryByRole('checkbox', { name: /content policy/ })).not.toBeInTheDocument();
    });

    it('links the terms and the content policy to their placeholder pages', async () => {
      setup();
      await screen.findByLabelText('Start date');

      expect(screen.getByRole('link', { name: 'Organizer terms' })).toHaveAttribute('href', '/en/organizer-terms');
      expect(screen.getByRole('checkbox', { name: 'I accept the Organizer terms (version 1).' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Promotion content policy' })).toHaveAttribute(
        'href',
        '/en/organizer-terms#content-policy',
      );
    });

    it('rejects a registry code with a bad check digit without asking the register', async () => {
      setup();
      await userEvent.type(await screen.findByLabelText('Registry code'), BAD_CODE);

      expect(screen.getByText('That isn’t a valid registry code. Check the 8 digits.')).toBeInTheDocument();
      expect(field('Registry code')).toHaveAttribute('aria-invalid', 'true');
      expect(mockPost).not.toHaveBeenCalled();
    });

    it('keeps only digits in the registry code', async () => {
      setup();
      await userEvent.type(await screen.findByLabelText('Registry code'), '12a3-4');
      expect(field('Registry code')).toHaveValue('1234');
    });
  });

  describe('registry lookup states (#617)', () => {
    it('fills the legal name from the register and locks it', async () => {
      setup();
      await screen.findByLabelText('Registry code');
      await userEvent.type(field('Registry code'), VALID_CODE);

      expect(await screen.findByText('Found in the business register.')).toBeInTheDocument();
      expect(field('Legal name')).toHaveValue('Kalamaja Kogukond MTÜ');
      expect(field('Legal name')).toHaveAttribute('readonly');
      expect(screen.getByText('Filled in from the business register. It can’t be edited.')).toBeInTheDocument();
      expect(mockPost).toHaveBeenCalledWith('/organizer/promotions/registry-lookup', { registry_code: VALID_CODE });
    });

    it('shows a busy state while the register is asked', async () => {
      let release: (v: unknown) => void = () => {};
      setup({ lookup: () => new Promise((resolve) => { release = resolve; }) });
      await userEvent.type(await screen.findByLabelText('Registry code'), VALID_CODE);

      expect(await screen.findByText('Looking up the business register…')).toBeInTheDocument();
      release({ registry_code: VALID_CODE, legal_name: 'Kalamaja Kogukond MTÜ' });
      expect(await screen.findByText('Found in the business register.')).toBeInTheDocument();
    });

    it.each([
      ['registry_company_deleted', 'This company is deleted from the business register, so it can’t buy a Promotion.'],
      ['registry_company_not_found', 'We couldn’t find that code in the business register. Check the digits.'],
      ['registry_invalid_code', 'That isn’t a valid registry code. Check the 8 digits.'],
    ])('refuses on %s and keeps the name editable but the form blocked', async (code, message) => {
      setup({ lookup: async () => { throw new ApiError(422, 'x', code); } });
      await userEvent.type(await screen.findByLabelText('Registry code'), VALID_CODE);

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(field('Registry code')).toHaveAttribute('aria-invalid', 'true');
      await fillDates();
      await userEvent.click(screen.getByRole('button', { name: /^Pay [€…]/ }));
      expect(await screen.findByText(/Fix the highlighted fields to continue\. Enter a valid registry code\./)).toBeInTheDocument();
      expect(mockPost).not.toHaveBeenCalledWith('/organizer/promotions/checkout', expect.anything());
    });

    it('fails closed on an outage: says so, offers the request with a typed name', async () => {
      setup({ lookup: async () => { throw new ApiError(503, 'x', 'registry_unavailable'); } });
      await userEvent.type(await screen.findByLabelText('Registry code'), VALID_CODE);

      const notice = await screen.findByText('Card payment needs a verified business. Send a request instead: enter the registry code and legal name, and we’ll check them by hand.');
      expect(notice).toBeInTheDocument();
      expect(screen.getAllByText('We can’t verify the business right now.').length).toBeGreaterThan(0);
      expect(screen.queryByRole('button', { name: /^Pay [€…]/ })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Pay by card instead' })).not.toBeInTheDocument();
      expect(field('Legal name')).not.toHaveAttribute('readonly');
    });
  });

  describe('Pay button and its fallbacks (#618)', () => {
    async function ready() {
      setup();
      await screen.findByLabelText('Start date');
      await fillDates('2026-10-29', '2026-11-03');
      await fillBusiness();
      await userEvent.click(screen.getByRole('checkbox', { name: /content policy/ }));
      await userEvent.click(screen.getByRole('checkbox', { name: /I accept the Organizer terms/ }));
    }

    it('makes Pay the primary action with the hold note and a quiet bank-transfer link', async () => {
      setup();
      await screen.findByLabelText('Start date');

      expect(screen.getByRole('button', { name: /^Pay [€…]/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Pay by bank transfer instead' })).toBeInTheDocument();
      expect(screen.getByText(/We hold your days for 30 minutes while you pay\./)).toBeInTheDocument();
      expect(screen.queryByLabelText(/Note for us/)).not.toBeInTheDocument();
    });

    it('starts checkout with the form values and leaves for Stripe’s page', async () => {
      await ready();
      await userEvent.type(field(/^Billing email/), 'arved@kalamaja.example');
      mockPost.mockReset();
      mockPost.mockImplementation(async (path: string, body?: unknown) =>
        path === '/organizer/promotions/checkout'
          ? { promotion_id: 9, checkout_url: 'https://checkout.stripe.com/c/pay/cs_1', expires_at: null }
          : { registry_code: (body as { registry_code: string }).registry_code, legal_name: 'Kalamaja Kogukond MTÜ' },
      );

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      await waitFor(() => expect(assign).toHaveBeenCalledWith('https://checkout.stripe.com/c/pay/cs_1'));
      expect(mockPost).toHaveBeenCalledWith('/organizer/promotions/checkout', {
        event_id: 5,
        start_date: '2026-10-29',
        end_date: '2026-11-03',
        registry_code: VALID_CODE,
        billing_email: 'arved@kalamaja.example',
        content_policy_attested: true,
        terms_accepted: true,
      });
    });

    it('shows “Opening secure checkout…” and blocks a second press while it starts', async () => {
      await ready();
      mockPost.mockReset();
      mockPost.mockImplementation(() => new Promise(() => {}));

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      const button = await screen.findByRole('button', { name: 'Opening secure checkout…' });
      expect(button).toBeDisabled();
    });

    it('starts on the request path with the review copy when the context says review is required', async () => {
      setup({ ctx: { review_required: true } });
      await screen.findByLabelText('Start date');

      expect(screen.getByText('This event needs a quick review before it can be promoted.')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^Pay [€…]/ })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Pay by card instead' })).not.toBeInTheDocument();
      expect(screen.getByLabelText(/Note for us/)).toBeInTheDocument();
    });

    it('starts on the request path when the context says card checkout is unavailable', async () => {
      setup({ ctx: { checkout_available: false } });
      await screen.findByLabelText('Start date');

      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^Pay [€…]/ })).not.toBeInTheDocument();
    });

    it('falls back to the request with the review message when the event needs review', async () => {
      await ready();
      mockPost.mockReset();
      mockPost.mockRejectedValue(new ApiError(409, 'This event needs a quick review before it can be promoted.', 'event_needs_review'));

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      expect(await screen.findByText('This event needs a quick review before it can be promoted.')).toBeInTheDocument();
      expect(screen.getByText(/Send a request instead\. We’ll look at the event and email you with a decision\. Nothing is charged\./)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Pay by card instead' })).not.toBeInTheDocument();
      expect(screen.getByLabelText(/Note for us/)).toBeInTheDocument();
    });

    it('falls back to the request when card checkout is switched off (404)', async () => {
      await ready();
      mockPost.mockReset();
      mockPost.mockRejectedValue(new ApiError(404, 'promotions_unavailable'));

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      expect(await screen.findByText(/Card payment isn’t available right now\. Send a request instead/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
    });

    it('treats a register outage reported by checkout like a lookup outage', async () => {
      await ready();
      mockPost.mockReset();
      mockPost.mockRejectedValue(new ApiError(503, 'x', 'registry_unavailable'));

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      expect(await screen.findAllByText('We can’t verify the business right now.')).not.toHaveLength(0);
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
    });

    it('words a refused checkout in the viewer’s language and refreshes the dates', async () => {
      await ready();
      mockPost.mockReset();
      mockPost.mockRejectedValue(new ApiError(409, 'English server text', 'overlap'));

      await userEvent.click(screen.getByRole('button', { name: 'Pay €37.20' }));

      expect(await screen.findByText('This event already has a Promotion in these dates.')).toBeInTheDocument();
      expect(screen.queryByText('English server text')).not.toBeInTheDocument();
    });

    it('lets the Organizer switch to the bank-transfer request and back to card', async () => {
      setup();
      await screen.findByLabelText('Start date');

      await userEvent.click(screen.getByRole('button', { name: 'Pay by bank transfer instead' }));
      expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument();
      expect(screen.getByLabelText(/Note for us/)).toBeInTheDocument();
      expect(screen.getByText(/We review requests by hand\./)).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Pay by card instead' }));
      expect(screen.getByRole('button', { name: /^Pay [€…]/ })).toBeInTheDocument();
    });

    it('sends the request with the terms accepted and shows the sent card', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await userEvent.click(screen.getByRole('button', { name: 'Pay by bank transfer instead' }));
      await fillDates('2026-10-29', '2026-11-03');
      await fillBusiness();
      await userEvent.type(field(/^Note for us/), 'Invoice to accounting please');
      await userEvent.click(screen.getByRole('checkbox', { name: /I accept the Organizer terms/ }));
      mockPost.mockImplementation(async (path: string, body?: unknown) =>
        path === '/organizer/promotions/requests'
          ? {
              id: 31,
              event_title: 'Kalamaja Open Doors',
              start_date: '2026-10-29',
              end_date: '2026-11-03',
              days: 6,
              advertiser_legal_name: 'Kalamaja Kogukond MTÜ',
              price: priceFor(6),
            }
          : { registry_code: (body as { registry_code: string }).registry_code, legal_name: 'Kalamaja Kogukond MTÜ' },
      );

      await userEvent.click(screen.getByRole('button', { name: 'Send request' }));

      expect(await screen.findByRole('heading', { name: 'Request sent' })).toBeInTheDocument();
      expect(mockPost).toHaveBeenCalledWith('/organizer/promotions/requests', {
        event_id: 5,
        start_date: '2026-10-29',
        end_date: '2026-11-03',
        advertiser_legal_name: 'Kalamaja Kogukond MTÜ',
        advertiser_registry_code: VALID_CODE,
        billing_email: null,
        note: 'Invoice to accounting please',
        terms_accepted: true,
      });
      const recap = screen.getByRole('status');
      expect(within(recap).getByText('29 Oct – 3 Nov · 6 days')).toBeInTheDocument();
      expect(within(recap).getByText('€37.20')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'View your Promotions' })).toHaveAttribute('href', '/en/organizer/promotions');
    });

    it('shows a daily-limit refusal in words', async () => {
      setup();
      await screen.findByLabelText('Start date');
      await userEvent.click(screen.getByRole('button', { name: 'Pay by bank transfer instead' }));
      await fillDates();
      await fillBusiness();
      await userEvent.click(screen.getByRole('checkbox', { name: /I accept the Organizer terms/ }));
      mockPost.mockImplementation(async (path: string) => {
        if (path === '/organizer/promotions/requests') throw new ApiError(429, 'Too many', 'daily_request_limit');
        return { registry_code: VALID_CODE, legal_name: 'Kalamaja Kogukond MTÜ' };
      });

      await userEvent.click(screen.getByRole('button', { name: 'Send request' }));

      expect(await screen.findByText('You’ve sent a lot of requests today. Try again tomorrow.')).toBeInTheDocument();
    });
  });
});
