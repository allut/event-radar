import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Feed from './Feed';
import { renderWithProviders, makeEvent } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => null),
  setLocale: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
  clearLocale: vi.fn(),
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
const mockPatch = vi.mocked(api.patch);

const feedResponse = {
  feed_date: '2024-07-15',
  events: [makeEvent({ id: 1, title: 'Event One' }), makeEvent({ id: 2, title: 'Event Two' })],
  built_at: '2024-07-15T06:00:00Z',
  is_stale: false,
};

describe('Feed', () => {
  it('shows loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText(/Failed to load your feed/i)).toBeInTheDocument());
  });

  it('shows empty state when events array is empty', async () => {
    mockGet.mockResolvedValueOnce({ feed_date: '2024-07-15', events: [], built_at: null });
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText(/your feed is being prepared/i)).toBeInTheDocument());
    expect(screen.queryAllByTestId('event-card').length).toBe(0);
  });

  it('renders event cards on success', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Event One')).toBeInTheDocument();
  });

  it('renders the explore promo as one band-wide link', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    const cta = await screen.findByRole('link', { name: /explore all events/i });
    expect(cta).toHaveAttribute('href', '/en/explore');
    // The band itself is the link — title and msg live inside it, so the
    // mobile layout can drop the button and stay fully tappable.
    expect(cta).toHaveTextContent(/more than five/i);
    // jsdom doesn't apply media queries, so this only exercises the desktop
    // name. Mobile hides the CTA span with clip-path (not display:none)
    // precisely so the accessible name asserted above holds at every width.
    expect(screen.getByText('Explore all events →')).toBeInTheDocument();
  });

  it('disables the locale selector while a locale switch PATCH is pending, guarding against a stale-mutation rollback race', async () => {
    // A locale switch refetches the feed under a new query key — resolve
    // every fetch, not just the first, so Feed (and its TopBar) stays
    // mounted with data across the switch instead of falling back to a
    // loading state that would unmount the locale selector being asserted on.
    mockGet.mockResolvedValue(feedResponse);
    let resolvePatch: () => void = () => undefined;
    mockPatch.mockReturnValueOnce(new Promise((resolve) => { resolvePatch = () => resolve(undefined); }));
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));

    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));
    await userEvent.click(screen.getByRole('button', { name: 'RU' }));

    // The switch navigates to /ru, remounting the bar with its menu closed.
    await userEvent.click(screen.getByRole('button', { name: 'Язык и тема' }));
    expect(screen.getByRole('button', { name: 'RU' })).toBeDisabled();

    resolvePatch();
    await waitFor(() => expect(screen.getByRole('button', { name: 'RU' })).not.toBeDisabled());
  });

  it('shows the stale-feed banner when is_stale is true', async () => {
    mockGet.mockResolvedValueOnce({ ...feedResponse, is_stale: true });
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText(/showing your latest feed/i)).toBeInTheDocument();
  });

  it('does not show the stale-feed banner when is_stale is false', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.queryByText(/showing your latest feed/i)).not.toBeInTheDocument();
  });

  it('logout clears the signed-in hint and navigates to landing', async () => {
    mockGet.mockResolvedValueOnce(feedResponse);
    const { clearSignedInHint } = await import('../../lib/auth');
    renderWithProviders(<Feed />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => screen.getByRole('button', { name: 'Account' }));
    await userEvent.click(screen.getByRole('button', { name: 'Account' }));
    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));
    expect(clearSignedInHint).toHaveBeenCalled();
  });
});
