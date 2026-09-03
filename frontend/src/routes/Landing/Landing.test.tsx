import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Landing from './Landing';
import { renderWithProviders, makeEvent } from '../../test/utils';
import { API } from '../../constants';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../../components/LocaleSelector', () => ({
  default: () => <div data-testid="locale-selector" />,
}));

vi.mock('../../lib/gtag', () => ({
  trackEvent: vi.fn(),
}));

let matchMediaReducedMotion = false;
beforeEach(() => {
  matchMediaReducedMotion = false;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('reduce') && matchMediaReducedMotion,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});

import { api } from '../../api/client';
import { trackEvent } from '../../lib/gtag';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);
const mockTrackEvent = vi.mocked(trackEvent);

const counts = {
  upcoming_count: 1008,
  venue_count: 205,
  furthest_date: '2027-01-15',
  cheapest_price: 1,
  tonight_is_fallback: false,
  tonight_events: [
    { title: 'Tonight One', starts_at: '2026-09-01T18:00:00Z', venue_name: 'Venue A' },
    { title: 'Tonight Two', starts_at: '2026-09-01T19:00:00Z', venue_name: 'Venue B' },
  ],
};

function mockGetByUrl(routes: Record<string, unknown>) {
  mockGet.mockImplementation((url: string) => {
    const match = Object.keys(routes).find((prefix) => url.startsWith(prefix));
    return Promise.resolve(match ? routes[match] : { events: [] });
  });
}

describe('Landing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetByUrl({
      [API.publicShowcase]: { events: [] },
      [API.publicCounts]: counts,
    });
  });

  it('renders the hero headline', async () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    expect(screen.getByRole('heading', { name: /leaving the house/i, level: 1 })).toBeInTheDocument();
  });

  it('renders a plate per showcase event', async () => {
    mockGetByUrl({
      [API.publicShowcase]: {
        events: [
          makeEvent({ id: 1, title: 'Showcase One' }),
          makeEvent({ id: 2, title: 'Showcase Two' }),
        ],
      },
      [API.publicCounts]: counts,
    });
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText('Showcase One')).toBeInTheDocument());
    expect(screen.getByText('Showcase Two')).toBeInTheDocument();
  });

  it('renders one image for a showcase event with an image_url', async () => {
    mockGetByUrl({
      [API.publicShowcase]: {
        events: [makeEvent({ id: 1, title: 'Showcase One', image_url: 'https://example.com/poster.jpg' })],
      },
      [API.publicCounts]: counts,
    });
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    const img = await screen.findByRole('img', { name: 'Showcase One' });
    expect(screen.getAllByRole('img', { name: 'Showcase One' })).toHaveLength(1);
    expect(img).toHaveAttribute('src', 'https://example.com/poster.jpg');
  });

  it('renders the category-gradient placeholder for a showcase event with no image_url', async () => {
    mockGetByUrl({
      [API.publicShowcase]: {
        events: [makeEvent({ id: 1, title: 'Showcase One', image_url: null })],
      },
      [API.publicCounts]: counts,
    });
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText('Showcase One')).toBeInTheDocument());
    expect(screen.queryByRole('img', { name: 'Showcase One' })).not.toBeInTheDocument();
  });

  it('renders the tonight ticker from /public/counts', async () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByTestId('ticker')).toBeInTheDocument());
    const ticker = within(screen.getByTestId('ticker'));
    // Duplicated in the DOM twice for the seamless marquee loop technique.
    expect(ticker.getAllByText(/Tonight One/).length).toBe(2);
    expect(ticker.getByText(/Tonight in Tallinn/i)).toBeInTheDocument();
  });

  it('renders the fallback ticker title when the backend widened the window', async () => {
    mockGetByUrl({
      [API.publicShowcase]: { events: [] },
      [API.publicCounts]: { ...counts, tonight_is_fallback: true },
    });
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText(/Coming up this week/i)).toBeInTheDocument());
  });

  it('duplicates ticker content for the marquee loop, but not under reduced motion', async () => {
    matchMediaReducedMotion = true;
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByTestId('ticker')).toBeInTheDocument());
    const ticker = within(screen.getByTestId('ticker'));
    expect(ticker.getAllByText(/Tonight One/).length).toBe(1);
  });

  it('renders the stat row from /public/counts', async () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getByText('1,008+')).toBeInTheDocument());
    expect(screen.getByText(/upcoming events/i)).toBeInTheDocument();
    expect(screen.getByText('205+')).toBeInTheDocument();
    expect(screen.getByText(/venues across Tallinn/i)).toBeInTheDocument();
    expect(screen.getByText('2027')).toBeInTheDocument();
    expect(screen.getByText(/furthest evening booked/i)).toBeInTheDocument();
  });

  it('renders the hero counter and brand mark', async () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    await waitFor(() => expect(screen.getAllByText('1,008').length).toBeGreaterThan(0));
    const venueCount = screen.getByText('205', { selector: 'b' });
    expect(venueCount.parentElement?.textContent).toMatch(/205 venues/i);
    expect(screen.getAllByText('2', { selector: 'b' }).length).toBeGreaterThan(0);
    expect(screen.getByText('Radar')).toBeInTheDocument();
  });

  it('submits the email capture and shows the inbox confirmation', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    const input = screen.getByPlaceholderText(/you@example.com/i);
    await userEvent.type(input, 'me@example.com');
    await userEvent.click(screen.getByRole('button', { name: /Get Daily 5/i }));
    await waitFor(() => expect(screen.getByText(/Check your inbox/i)).toBeInTheDocument());
    expect(mockPost).toHaveBeenCalledWith('/auth/request-link', { email: 'me@example.com', locale: 'en' });
  });

  it('renders the organizer band linking to the organizer login', () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    expect(screen.getByRole('heading', { name: /Put your event on the radar/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /List your event/i })).toHaveAttribute('href', '/en/organizer/login');
  });

  it('shows Explore in the nav for a signed-out visitor (TopBar\'s shared signed-out chrome, issue #235)', () => {
    renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
    expect(screen.getByRole('link', { name: 'Explore' })).toHaveAttribute('href', '/en/explore');
  });

  describe('showcase pill + analytics (issue #235)', () => {
    it('renders the "Explore all N events" pill beneath the showcase with the live count', async () => {
      renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
      const pill = await screen.findByRole('link', { name: /Explore all 1,008 events/i });
      expect(pill).toHaveAttribute('href', '/en/explore');
    });

    it('tracks landing_browse_cta_click when the pill is clicked', async () => {
      renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
      const pill = await screen.findByRole('link', { name: /Explore all 1,008 events/i });
      await userEvent.click(pill);
      expect(mockTrackEvent).toHaveBeenCalledWith('landing_browse_cta_click', { locale: 'en' });
    });

    it('tracks landing_browse_cta_click when the hero browse CTA is clicked', async () => {
      renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
      await userEvent.click(screen.getByRole('link', { name: /See what's on/i }));
      expect(mockTrackEvent).toHaveBeenCalledWith('landing_browse_cta_click', { locale: 'en' });
    });

    it('tracks landing_email_submit when the hero email-capture form is submitted', async () => {
      mockPost.mockResolvedValueOnce(undefined);
      renderWithProviders(<Landing />, { route: '/en', pathPattern: '/:locale' });
      await userEvent.type(screen.getByPlaceholderText(/you@example.com/i), 'me@example.com');
      await userEvent.click(screen.getByRole('button', { name: /Get Daily 5/i }));
      expect(mockTrackEvent).toHaveBeenCalledWith('landing_email_submit', { locale: 'en' });
    });
  });
});
