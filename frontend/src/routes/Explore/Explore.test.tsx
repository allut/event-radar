import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Explore from './Explore';
import { renderWithProviders, makeEvent } from '../../test/utils';
import type { EventData } from '../../components/EventCard';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event, index, onFeedbackBlocked, onCardClick }: {
    event: { id: number; title: string };
    index: number;
    onFeedbackBlocked?: (signal: string) => void;
    onCardClick?: (index: number) => void;
  }) => (
    <div data-testid="event-card">
      {event.title}
      {onFeedbackBlocked && (
        <button onClick={() => onFeedbackBlocked('bookmark')}>block-bookmark-{event.id}</button>
      )}
      {onCardClick && <button onClick={() => onCardClick(index)}>card-click-{event.id}</button>}
    </div>
  ),
}));

vi.mock('../../lib/gtag', () => ({
  trackEvent: vi.fn(),
}));

import { api } from '../../api/client';
import { trackEvent } from '../../lib/gtag';
import { isAuthenticated } from '../../lib/auth';
const mockGet = vi.mocked(api.get);
const mockTrackEvent = vi.mocked(trackEvent);
const mockIsAuthenticated = vi.mocked(isAuthenticated);

interface ExploreResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

function exploreResponse(
  events: EventData[],
  opts: Partial<Pick<ExploreResponse, 'total' | 'offset' | 'has_more'>> = {},
): ExploreResponse {
  return {
    events,
    total: opts.total ?? events.length,
    limit: 24,
    offset: opts.offset ?? 0,
    has_more: opts.has_more ?? false,
  };
}

const currentUser = { preferred_categories: ['music'], preferred_vibes: ['trendy'] };

beforeEach(() => {
  mockGet.mockReset();
  mockTrackEvent.mockClear();
  mockIsAuthenticated.mockReturnValue(true);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Explore', () => {
  it('renders event grid from the API', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(
        exploreResponse([makeEvent({ id: 1, title: 'Jazz Night' }), makeEvent({ id: 2, title: 'Art Show' })]),
      );
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Jazz Night')).toBeInTheDocument();
  });

  it('fresh load defaults to All events with every category/vibe chip selected', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Categories · 14/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Vibes · 10/ })).toBeInTheDocument();

    const calls = mockGet.mock.calls.map((c) => c[0] as string);
    const exploreCall = calls.find((c) => c.startsWith('/explore'));
    expect(exploreCall).toBeDefined();
    expect(exploreCall).not.toContain('category=');
    expect(exploreCall).not.toContain('vibe=');
    expect(exploreCall).toContain('for_you=false');
  });

  it('deselecting a category chip narrows the query while staying on All events', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('category='));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).not.toMatch(/category=[^&]*\bmusic\b/);
    });
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('deselecting every category chip shows no results and skips the request', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore?category=', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getByText(/no events/i)).toBeInTheDocument());

    const calls = mockGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((c) => c.startsWith('/explore'))).toBe(false);
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
  });

  it('load more fetches the next page and appends results', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      if (path.includes('offset=1')) {
        return Promise.resolve(exploreResponse([makeEvent({ id: 2, title: 'Second Event' })], { total: 2, offset: 1 }));
      }
      return Promise.resolve(
        exploreResponse([makeEvent({ id: 1, title: 'First Event' })], { total: 2, offset: 0, has_more: true }),
      );
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

    await userEvent.click(screen.getByRole('button', { name: /load more/i }));

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Second Event')).toBeInTheDocument();
  });

  it('switching to For you presets chips to the persona taste and personalizes', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: 'For you' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByRole('button', { name: /Categories · 1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Vibes · 1/ })).toBeInTheDocument();

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('for_you=true'));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).toContain('category=music');
      expect(exploreCall).toContain('vibe=trendy');
    });
  });

  it('selecting a category outside the user\'s taste while in For-you auto-flips to All events, keeping the prior selection plus the new chip', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser); // taste: music/trendy only
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true'));

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false'));
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Categories · 2/ })).toBeInTheDocument();

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      const exploreCall = calls.find((c) => c.startsWith('/explore') && c.includes('theater'));
      expect(exploreCall).toBeDefined();
      expect(exploreCall).toContain('music');
    });
  });

  it('removing an in-taste chip while in For-you does not flip the switch off', async () => {
    const currentUserMulti = { preferred_categories: ['music', 'theater'], preferred_vibes: ['trendy'] };
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUserMulti);
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 2/ })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Categories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));

    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('switching back to All events reselects every category/vibe chip', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 1/ })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'All events' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /Categories · 14/ })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Vibes · 10/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.reject(new Error('network'));
    });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

    await waitFor(() => expect(screen.getByText(/Failed to load events/i)).toBeInTheDocument());
  });

  describe('prerender readiness marker (issue #236)', () => {
    it('is absent while the query is loading', () => {
      mockGet.mockImplementation(() => new Promise(() => {})); // never resolves
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      expect(document.querySelector('[data-prerender-ready="true"]')).toBeNull();
    });

    it('is present, with no error marker, once the query succeeds', async () => {
      mockGet.mockImplementation((path: string) => {
        if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
        return Promise.resolve(exploreResponse([makeEvent({ id: 1 })]));
      });
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

      await waitFor(() => expect(document.querySelector('[data-prerender-ready="true"]')).not.toBeNull());
      expect(document.querySelector('[data-prerender-error="true"]')).toBeNull();
    });

    it('is present alongside the error marker once the query errors, so the build can fail loudly instead of timing out', async () => {
      mockGet.mockImplementation((path: string) => {
        if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
        return Promise.reject(new Error('network'));
      });
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

      await waitFor(() => expect(document.querySelector('[data-prerender-ready="true"]')).not.toBeNull());
      expect(document.querySelector('[data-prerender-error="true"]')).not.toBeNull();
    });
  });

  it('a chip click during a pending search debounce does not clobber it', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.startsWith('/users/me')) return Promise.resolve(currentUser);
      return Promise.resolve(exploreResponse([]));
    });

    // Real timers made this test's debounce wait flaky under a loaded CI
    // runner (timeout races against the actual 400ms clock). Fake timers +
    // userEvent's advanceTimers option drive the debounce deterministically
    // instead — same pattern as utils.test.ts / useToast.test.ts / Settings.test.tsx.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });

    renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
    await waitFor(() => expect(screen.getByRole('button', { name: /Categories/ })).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/search events/i), 'jazz');
    await user.click(screen.getByRole('button', { name: /Categories/ }));
    await user.click(screen.getByRole('button', { name: 'Music' }));

    // Wait past the debounce window — both the typed text and the chip click
    // (made while the debounce was still pending) must land in the committed
    // query, not just whichever one the debounce effect's closure captured.
    // Deselecting the (default-checked) Music chip narrows the category param;
    // the assertion below just needs to see both the typed text and the
    // narrowed category param land in the same committed query.
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      // Assert on the *final* committed /explore query, not the first q=jazz
      // call. Under load the debounce may not coalesce the typed text and the
      // mid-debounce chip toggle into one window, emitting a transient q=jazz
      // call before the narrowed category lands. "No clobber" is a property
      // of the settled query, so check the last committed call.
      const exploreCalls = calls.filter((c) => c.startsWith('/explore'));
      const exploreCall = exploreCalls[exploreCalls.length - 1];
      expect(exploreCall).toContain('q=jazz');
      expect(exploreCall).toMatch(/category=/);
      expect(exploreCall).not.toMatch(/category=[^&]*\bmusic\b/);
    });
  });

  describe('anonymous visitor (issue #235)', () => {
    beforeEach(() => {
      mockIsAuthenticated.mockReturnValue(false);
    });

    it('never calls /users/me when signed out', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([makeEvent({ id: 1 }), makeEvent({ id: 2 })])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      // Anonymous grid drops the last event to make room for the upsell
      // card without an orphaned card wrapping to a new row.
      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

      const calls = mockGet.mock.calls.map((c) => c[0] as string);
      expect(calls.some((c) => c.startsWith('/users/me'))).toBe(false);
    });

    it('fires explore_view with signed_in: false on landing', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(mockTrackEvent).toHaveBeenCalledWith('explore_view', { signed_in: false, locale: 'en' }));
    });

    it('renders the persistent upsell card and opens the sign-in modal from its CTA', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([makeEvent({ id: 1 })])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getByText('Like what you see?')).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'Sign in to personalize →' }));

      expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument();
      expect(screen.getByText('Sign in for your picks')).toBeInTheDocument();
      expect(mockTrackEvent).toHaveBeenCalledWith('explore_upsell_click', { action: 'for_you' });
      expect(mockTrackEvent).toHaveBeenCalledWith('signin_modal_open', { trigger: 'for_you' });
    });

    it('intercepts a blocked feedback press into the save/thumbs sign-in modal without a second trigger reopening it', async () => {
      mockGet.mockImplementation(() =>
        Promise.resolve(exploreResponse([
          makeEvent({ id: 1, title: 'First' }),
          makeEvent({ id: 2, title: 'Second' }),
          makeEvent({ id: 3, title: 'Third' }),
        ])),
      );
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      // Anonymous grid drops the last event to make room for the upsell
      // card without an orphaned card wrapping to a new row.
      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));

      await userEvent.click(screen.getByText('block-bookmark-1'));
      expect(screen.getByText('Sign in to save this')).toBeInTheDocument();
      expect(mockTrackEvent).toHaveBeenCalledWith('explore_upsell_click', { action: 'save' });
      expect(mockTrackEvent).toHaveBeenCalledWith('signin_modal_open', { trigger: 'save' });

      mockTrackEvent.mockClear();
      // A second trigger click while the modal is open is a no-op — no
      // second signin_modal_open, and the modal keeps its original copy.
      await userEvent.click(screen.getByText('block-bookmark-2'));
      expect(mockTrackEvent).not.toHaveBeenCalledWith('signin_modal_open', expect.anything());
      expect(screen.getByText('Sign in to save this')).toBeInTheDocument();
    });

    it('fires explore_card_click with signed_in and position when a card is opened', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([makeEvent({ id: 1 }), makeEvent({ id: 2 })])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      // Anonymous grid drops the last event to make room for the upsell
      // card without an orphaned card wrapping to a new row.
      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));

      await userEvent.click(screen.getByText('card-click-1'));

      expect(mockTrackEvent).toHaveBeenCalledWith('explore_card_click', { signed_in: false, position: 0 });
    });

    it('turning on For-you intercepts into the sign-in modal instead of applying the filter', async () => {
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse([])));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });
      await waitFor(() => expect(screen.getByRole('button', { name: 'For you' })).toBeInTheDocument());

      await userEvent.click(screen.getByRole('button', { name: 'For you' }));

      expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'false');
    });

    it('drops the last event to keep the total card count unchanged when the upsell card is added', async () => {
      const anonEvents = Array.from({ length: 6 }, (_, i) => makeEvent({ id: i + 1, title: `Event ${i + 1}` }));
      mockGet.mockImplementation(() => Promise.resolve(exploreResponse(anonEvents)));
      renderWithProviders(<Explore />, { route: '/en/explore', pathPattern: '/:locale/explore' });

      await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(5));
      expect(screen.queryByText('Event 6')).not.toBeInTheDocument();
      expect(screen.getByText('Like what you see?')).toBeInTheDocument();
    });
  });
});
