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

function sampleResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    event: {
      id: 42,
      title_orig: 'Jazz Cellar Night',
      description_orig: 'A late-night jazz set.',
      important_info: null,
      status: 'published',
      dedup_group_id: null,
      submitted_by_organizer_id: null,
      needs_review: false,
      cancellation_reason: null,
      created_at: '2026-08-20T04:12:00+03:00',
      updated_at: '2026-08-24T06:03:00+03:00',
      detail_refetched_at: null,
      classification: {
        categories: ['music'],
        vibes: ['underground'],
        quality_score: 0.82,
        why_go_bullets: ['Great sound'],
        language_detected: 'en',
        model_used: 'llama-3.3-70b-versatile',
        classified_at: '2026-08-20T04:15:00+03:00',
      },
    },
    dedup_siblings: [],
    reports: [],
    raw_events: [],
    in_todays_feed: false,
    ...overrides,
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

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night' })).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledWith('/admin/events/42');
    expect(screen.getByText('published')).toBeInTheDocument();
    expect(screen.getByText('A late-night jazz set.')).toBeInTheDocument();
  });

  it('renders organizer-authored HTML in description/important_info as real markup, sanitized', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({
        event: {
          ...sampleResponse().event,
          description_orig: '<p>Doors at <strong>8pm</strong>.</p><h3>Program</h3><ul><li>Set one</li></ul><script>alert(1)</script>',
          important_info: '<p>18+ only. <a href="https://example.com">Details</a></p>',
        },
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night' })).toBeInTheDocument());

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
      sampleResponse({ event: { ...sampleResponse().event, description_orig: null } }),
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

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night' })).toBeInTheDocument());
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
      sampleResponse({ event: { ...sampleResponse().event, needs_review: true, submitted_by_organizer_id: 7 } }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Retract' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument();
  });

  it('hides approve/retract when needs_review is true but there is no organizer submission', async () => {
    mockGet.mockResolvedValueOnce(
      sampleResponse({ event: { ...sampleResponse().event, needs_review: true, submitted_by_organizer_id: null } }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night' })).toBeInTheDocument());
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
        event: { ...sampleResponse().event, dedup_group_id: 7 },
        dedup_siblings: [
          { id: 43, title: 'Jazz Night (Trio Set)', starts_at: '2026-08-29T19:00:00+03:00', venue: 'Cellar', status: 'draft', url: null, is_explicit: false },
        ],
      }),
    );
    renderWithProviders(<AdminEventDetail eventId="42" />, { route: '/admin/events/42' });

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Jazz Cellar Night' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('tab', { name: /Dedup & reports/ }));

    const link = screen.getByRole('link', { name: /Jazz Night \(Trio Set\)/ });
    expect(link).toHaveAttribute('href', '/admin/events/43');
  });
});
