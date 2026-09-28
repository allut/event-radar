import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerDashboard from './OrganizerDashboard';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockDelete = vi.mocked(organizerApi.delete);

const sampleEvents = {
  events: [
    { id: 1, slug: 'jazz-night', title: 'Jazz Night', starts_at: '2026-08-01T18:00:00Z', status: 'published', needs_review: true },
    { id: 2, slug: 'art-show', title: 'Art Show', starts_at: '2026-08-05T10:00:00Z', status: 'classified', needs_review: true },
  ],
  limit: 24,
  offset: 0,
};

// OrganizerDashboard renders OrganizerProfileNudge, which fires its own
// organizerApi.get('/organizer/profile') call — route by path instead of
// queueing positional mockResolvedValueOnce values, since the two calls can
// resolve in either order. Defaults to a name set, so the nudge banner
// (covered by OrganizerProfileNudge.test.tsx) doesn't interfere with these
// event-list assertions unless a test overrides it.
// ClaimEventPicker (#414) also fires its own organizerApi.get calls
// (suggestions on mount) — defaults to an empty list so it doesn't leak
// duplicate event titles into these event-list assertions unless a test
// overrides it.
function mockOrganizerGet(
  eventsResponse: unknown,
  profileResponse: unknown = { name: 'Test Organizer' },
  claimSuggestionsResponse: unknown = { events: [] },
  ownClaimsResponse: unknown = { claims: [] },
) {
  mockGet.mockImplementation((path: string) => {
    if (path.includes('/organizer/profile')) return Promise.resolve(profileResponse);
    if (path.includes('/organizer/claims/suggestions')) return Promise.resolve(claimSuggestionsResponse);
    if (path.startsWith('/organizer/claims?')) return Promise.resolve(ownClaimsResponse);
    return Promise.resolve(eventsResponse);
  });
}

beforeEach(() => {
  mockGet.mockReset();
  mockDelete.mockReset();
});

describe('OrganizerDashboard', () => {
  it('lists the organizer\'s own events with status and review badges', async () => {
    mockOrganizerGet(sampleEvents);
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.getByText('Art Show')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/organizer/events?limit='));
  });

  it('sends locale= on the events and own-claims requests (#454)', async () => {
    mockOrganizerGet(sampleEvents, undefined, undefined, { claims: [] });
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/\/organizer\/events\?.*[?&]locale=en/));
    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/^\/organizer\/claims\?locale=en/));
  });

  it('shows an empty state when there are no events', async () => {
    mockOrganizerGet({ events: [], limit: 24, offset: 0 });
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText(/no events yet/i)).toBeInTheDocument());
  });

  it('deletes an event after confirmation', async () => {
    mockOrganizerGet(sampleEvents);
    mockDelete.mockResolvedValueOnce({ id: 1, status: 'cancelled' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    await userEvent.click(deleteButtons[0]);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/organizer/events/1'));
    confirmSpy.mockRestore();
  });

  it('does not delete when the confirmation is declined', async () => {
    mockOrganizerGet(sampleEvents);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    await userEvent.click(deleteButtons[0]);

    expect(mockDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('shows a "Your claims" section with status and shortcuts, hidden when there are none', async () => {
    mockOrganizerGet(sampleEvents, undefined, undefined, {
      claims: [
        {
          id: 1,
          kind: 'publisher',
          status: 'approved',
          verification_mechanism: 'fienta_token',
          dormant: false,
          publisher_name: 'Jazzkaar',
          event_id: 42,
          event_title: 'Jazzkaar Festival Night',
          created_at: '2026-08-01T00:00:00Z',
          resolved_at: '2026-08-02T00:00:00Z',
        },
        {
          id: 2,
          kind: 'series',
          status: 'declined',
          verification_mechanism: null,
          dormant: false,
          publisher_name: null,
          event_id: null,
          event_title: null,
          created_at: '2026-08-01T00:00:00Z',
          resolved_at: '2026-08-03T00:00:00Z',
        },
      ],
    });
    renderWithProviders(<OrganizerDashboard />);

    await waitFor(() => expect(screen.getByText('Your claims')).toBeInTheDocument());
    expect(screen.getByText('Jazzkaar Festival Night')).toBeInTheDocument();
    expect(screen.getByText('Granted')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit event' })).toHaveAttribute(
      'href',
      expect.stringContaining('/organizer/claims/1/edit'),
    );
    expect(screen.getByText('Declined')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'View status' })[0]).toHaveAttribute(
      'href',
      expect.stringContaining('/organizer/claims/2/pending'),
    );
  });

  it('hides the "Your claims" section when the organizer has no claims', async () => {
    mockOrganizerGet(sampleEvents);
    renderWithProviders(<OrganizerDashboard />);
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.queryByText('Your claims')).not.toBeInTheDocument();
  });
});
