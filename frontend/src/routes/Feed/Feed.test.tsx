import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Feed from './Feed';
import { renderWithProviders, makeEvent } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event }: { event: { title: string } }) => <div data-testid="event-card">{event.title}</div>,
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);

const feedResponse = {
  feed_date: '2024-07-15',
  events: [makeEvent({ id: 1, title: 'Event One' }), makeEvent({ id: 2, title: 'Event Two' })],
  built_at: '2024-07-15T06:00:00Z',
  is_stale: false,
};

describe('Feed', () => {
  it('shows loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Feed />);
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<Feed />);
    await waitFor(() => expect(screen.getByText(/Failed to load your feed/i)).toBeInTheDocument());
  });

  it('shows empty state when events array is empty', async () => {
    mockGet.mockResolvedValueOnce({ feed_date: '2024-07-15', events: [], built_at: null });
    renderWithProviders(<Feed />);
    await waitFor(() => expect(screen.getByText(/your feed is being prepared/i)).toBeInTheDocument());
    expect(screen.queryAllByTestId('event-card').length).toBe(0);
  });

  it('renders event cards on success', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />);
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Event One')).toBeInTheDocument();
  });

  it('renders the explore promo as one band-wide link', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />);
    const cta = await screen.findByRole('link', { name: /explore all events/i });
    expect(cta).toHaveAttribute('href', '/explore');
    // The band itself is the link — title and msg live inside it, so the
    // mobile layout can drop the button and stay fully tappable.
    expect(cta).toHaveTextContent(/more than five/i);
    // jsdom doesn't apply media queries, so this only exercises the desktop
    // name. Mobile hides the CTA span with clip-path (not display:none)
    // precisely so the accessible name asserted above holds at every width.
    expect(screen.getByText('Explore all events →')).toBeInTheDocument();
  });

  it('shows the stale-feed banner when is_stale is true', async () => {
    mockGet.mockResolvedValueOnce({ ...feedResponse, is_stale: true });
    renderWithProviders(<Feed />);
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText(/showing your latest feed/i)).toBeInTheDocument();
  });

  it('does not show the stale-feed banner when is_stale is false', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />);
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.queryByText(/showing your latest feed/i)).not.toBeInTheDocument();
  });

  it('logout clears the signed-in hint and navigates to landing', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    const { clearSignedInHint } = await import('../../lib/auth');
    renderWithProviders(<Feed />);
    await waitFor(() => screen.getByRole('button', { name: /sign out/i }));
    await userEvent.click(screen.getByRole('button', { name: /sign out/i }));
    expect(clearSignedInHint).toHaveBeenCalled();
  });
});
