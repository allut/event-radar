import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminEventDetail from './AdminEventDetail';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

// eventOverrides patches the base event; contentByLocale, when omitted, is
// derived from the (possibly overridden) title/description/important_info/
// venue_name — et marked as a real translation, en/ru as fallbacks — so most
// tests never need to touch content_by_locale directly.
function sampleResponse(overrides: {
  event?: Partial<Record<string, unknown>>;
  contentByLocale?: Record<string, unknown>;
  [key: string]: unknown;
} = {}) {
  const { event: eventOverrides, contentByLocale, ...rest } = overrides;
  const baseEvent = {
    id: 42,
    title_orig: 'Jazz Cellar Night',
    description_orig: 'A late-night jazz set.',
    important_info: null as string | null,
    status: 'published',
    dedup_group_id: null,
    submitted_by_organizer_id: null,
    needs_review: false,
    cancellation_reason: null,
    created_at: '2026-08-20T04:12:00+03:00',
    updated_at: '2026-08-24T06:03:00+03:00',
    detail_refetched_at: null,
    starts_at: '2026-08-29T19:00:00+03:00',
    ends_at: null,
    venue_name: 'Cellar',
    venue_address: 'Cellar Street 1',
    lat: 59.43,
    lng: 24.75,
    url: 'https://example.com/event',
    image_url: null as string | null,
    price_min: null,
    price_max: null,
    currency: null,
    price_hint: null,
    has_free_tier: false,
    is_explicit: false,
    is_out_of_area: false,
    is_non_event: false,
    geocode_attempted_at: null,
    classification: {
      categories: ['music'],
      vibes: ['underground'],
      quality_score: 0.82,
      why_go_bullets: ['Great sound'],
      language_detected: 'en',
      model_used: 'llama-3.3-70b-versatile',
      classified_at: '2026-08-20T04:15:00+03:00',
    },
  };
  const event = { ...baseEvent, ...eventOverrides };
  const fallbackSlot = {
    title: event.title_orig,
    description: event.description_orig,
    important_info: event.important_info,
    venue_name: event.venue_name,
    translated: { title: false, description: false, important_info: false },
  };
  const defaultContentByLocale = {
    et: { ...fallbackSlot, translated: { title: true, description: true, important_info: true } },
    en: fallbackSlot,
    ru: fallbackSlot,
  };
  return {
    event: { ...event, content_by_locale: contentByLocale ?? defaultContentByLocale },
    dedup_siblings: [],
    reports: [],
    raw_events: [],
    in_todays_feed: false,
    ...rest,
  };
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('AdminEventDetail', () => {
  it('renders the curated event payload on the Overview tab', async () => {
    mockGet.mockResolvedValueOnce(sampleResponse());
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/admin/events/42');
    expect(screen.getByText('published')).toBeInTheDocument();
    expect(screen.getByText('A late-night jazz set.')).toBeInTheDocument();
  });

  it('renders organizer-authored HTML in description/important_info as real markup, sanitized', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        event: {
          description_orig: '<p>Doors at <strong>8pm</strong>.</p><h3>Program</h3><ul><li>Set one</li></ul><script>alert(1)</script>',
          important_info: '<p>18+ only. <a href="https://example.com">Details</a></p>',
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());

    expect(screen.getByRole('heading', { name: 'Program', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('listitem')).toHaveTextContent('Set one');
    expect(screen.getByText('8pm').tagName).toBe('STRONG');
    expect(document.querySelector('script')).not.toBeInTheDocument();

    const link = screen.getByRole('link', { name: 'Details' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('shows a plain-text fallback when there is no description', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({ event: { description_orig: null } }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByText('No description.')).toBeInTheDocument());
  });

  it('shows the feed-membership badge only when in_todays_feed is true', async () => {
    mockGet.mockResolvedValueOnce(sampleResponse({ in_todays_feed: true }));
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByText(/In today.s Daily 5/)).toBeInTheDocument());
  });

  it('shows an error state when the event fails to load', async () => {
    mockGet.mockRejectedValueOnce(new ApiError(404, 'Event not found.'));
    renderWithProviders(<AdminEventDetail eventId="999" />, { route: '/admin/events/999' });

    await waitFor(() => expect(screen.getByText("Couldn't load this event.")).toBeInTheDocument());
  });

  it('renders raw payloads as escaped text, never as HTML', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        raw_events: [
          {
            id: 1,
            source_slug: 'fienta',
            external_id: 'ext-1',
            payload: { title: '<script>alert(1)</script>' },
            fetched_at: '2026-08-20T04:10:00+03:00',
            processed_at: null,
          },
        ],
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: /Raw payload/ }));

    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(document.querySelector('script')).not.toBeInTheDocument();
  });

  it('shows resolve/takedown actions only when there are open reports', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        reports: [
          { id: 1, user_id: 1, reason: 'spam_or_scam', is_illegal_allegation: false, detail: null, status: 'open', resolution_note: null, created_at: '2026-08-20T00:00:00Z', resolved_at: null },
        ],
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Resolve' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Take down event' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('shows approve/retract actions only when needs_review is true and it is an organizer submission', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({ event: { needs_review: true, submitted_by_organizer_id: 7 } }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Retract' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument();
  });

  it('hides approve/retract when needs_review is true but there is no organizer submission', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({ event: { needs_review: true, submitted_by_organizer_id: null } }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retract' })).not.toBeInTheDocument();
  });

  it('resolves open reports with the typed note and refetches', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        reports: [
          { id: 1, user_id: 1, reason: 'spam_or_scam', is_illegal_allegation: false, detail: null, status: 'open', resolution_note: null, created_at: '2026-08-20T00:00:00Z', resolved_at: null },
        ],
      }),
    );
    mockPost.mockResolvedValueOnce({ event_id: 42, resolved_count: 1 });
    mockGet.mockResolvedValueOnce(sampleResponse({ reports: [] }));
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Resolve' })).toBeDisabled());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Checked, all fine.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/admin/reports/42/resolve', { resolution_note: 'Checked, all fine.' }));
    expect(await screen.findByText('Resolved.')).toBeInTheDocument();
  });

  it('shows an error toast when an action fails', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        reports: [
          { id: 1, user_id: 1, reason: 'spam_or_scam', is_illegal_allegation: false, detail: null, status: 'open', resolution_note: null, created_at: '2026-08-20T00:00:00Z', resolved_at: null },
        ],
      }),
    );
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Resolve' })).toBeDisabled());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Checked, all fine.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
  });

  it('links dedup siblings to their own inspector page', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        event: { dedup_group_id: 7 },
        dedup_siblings: [
          { id: 43, title: 'Jazz Night (Trio Set)', starts_at: '2026-08-29T19:00:00+03:00', venue: 'Cellar', status: 'draft', url: null, is_explicit: false },
        ],
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: /Dedup & reports/ }));

    const link = screen.getByRole('link', { name: /Jazz Night \(Trio Set\)/ });
    expect(link).toHaveAttribute('href', '/admin/events/43');
  });

  it('renders the record fact list with starts/venue/price/image', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        event: {
          price_min: 5,
          price_max: 12,
          currency: 'EUR',
          image_url: 'https://example.com/poster.jpg',
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());

    expect(screen.getByText('Cellar')).toBeInTheDocument();
    expect(screen.getByText('5 – 12 EUR')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://example.com/poster.jpg');
    expect(screen.getByText('https://example.com/poster.jpg')).toBeInTheDocument();
  });

  it('switches the rendered title/description when the language switch moves to RU', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        contentByLocale: {
          et: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: true, description: true, important_info: true },
          },
          en: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
          ru: {
            title: 'Ночь джаза в подвале',
            description: 'Поздний джазовый сет.',
            important_info: null,
            venue_name: 'Погреб',
            translated: { title: true, description: true, important_info: false },
          },
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByText('A late-night jazz set.')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /^RU/ }));

    expect(await screen.findByText('Ночь джаза в подвале')).toBeInTheDocument();
    expect(screen.getByText('Поздний джазовый сет.')).toBeInTheDocument();
  });

  it('shows a fallback tag when the selected locale has no real translation', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        contentByLocale: {
          et: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: true, description: true, important_info: true },
          },
          en: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
          ru: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByText('A late-night jazz set.')).toBeInTheDocument());
    expect(screen.queryByText('fallback')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^EN/ }));

    expect(await screen.findAllByText('fallback')).not.toHaveLength(0);
  });

  it('never shows a fallback tag on the base (et) locale, even when its translated flags are false', async () => {
    // Mirrors an ingestion path where title_localized/etc. never got an
    // 'et' key (e.g. newsletter-derived events) — translated comes back
    // false for et, but et's content is still the canonical original, not
    // a fallback, and must not be tagged as one.
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        contentByLocale: {
          et: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
          en: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
          ru: {
            title: 'Jazz Cellar Night',
            description: 'A late-night jazz set.',
            important_info: null,
            venue_name: 'Cellar',
            translated: { title: false, description: false, important_info: false },
          },
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByText('A late-night jazz set.')).toBeInTheDocument());
    expect(screen.queryByText('fallback')).not.toBeInTheDocument();
  });
  it('offers the Grant Promotion form on the Promotions tab, listing the event\u2019s existing Promotions', async () => {
    const context = {
      event_id: 42,
      event_title: 'Jazz Cellar Night',
      owner: { organizer_id: 9, name: 'Example Jazz Club MTÜ', email: null },
      prefill: { advertiser_legal_name: 'Example Jazz Club MTÜ', billing_email: null },
      today: '2026-10-17',
      earliest_start: '2026-10-18',
      event_last_day: '2026-10-30',
      rules: { min_days: 3, max_days: 14, cap: 5, cap_strip_days: 14 },
      pricing: { day_price_cents: 500, vat_rate_percent: '24.00' },
      promotions: [
        {
          id: 1, event_id: 42, event_title: 'Jazz Cellar Night', organizer_name: 'Example Jazz Club MTÜ',
          status: 'paid', state: 'scheduled', start_date: '2026-10-20', end_date: '2026-10-22', days: 3,
          net_price_cents: 1500, vat_rate_percent: '24.00', vat_cents: 360, gross_price_cents: 1860,
          is_complimentary: false, complimentary_note: null, invoice_reference: null,
          advertiser_legal_name: 'Example Jazz Club MTÜ',
        },
      ],
    };
    mockGet.mockImplementation(async (path: string) => {
      if (path.includes('/promotion-context')) return context;
      if (path.startsWith('/admin/promotions/cap-strip')) return { today: '2026-10-17', cap: 5, days: [] };
      return sampleResponse();
    });
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night', level: 1 })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: 'Promotions' }));

    expect(await screen.findByText('20\u201322 Oct')).toBeInTheDocument();
    expect(screen.getByLabelText('Start date')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant Promotion' })).toBeDisabled();
  });
});
