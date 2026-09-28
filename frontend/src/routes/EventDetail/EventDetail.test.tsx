import { afterEach, describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventDetail from './EventDetail';
import { renderWithProviders, makeEvent } from '../../test/utils';
import { ORGANIZER_SIGNED_IN_HINT_KEY } from '../../constants';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => null),
  setLocale: vi.fn(),
  clearLocale: vi.fn(),
  isAuthenticated: vi.fn(() => true),
  subscribeAuth: vi.fn(() => () => undefined),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
  organizerApi: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('../../hooks/useFeedback', () => ({
  useFeedback: vi.fn(() => ({
    activeSignal: null,
    pending: false,
    sendFeedback: vi.fn(),
  })),
}));

vi.mock('../../utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils')>();
  return {
    ...actual,
    trackExternalClick: vi.fn(),
  };
});

import { api, organizerApi } from '../../api/client';
import { isAuthenticated } from '../../lib/auth';
const mockGet = vi.mocked(api.get);
const mockIsAuthenticated = vi.mocked(isAuthenticated);

const eventData = {
  ...makeEvent({
    id: 1,
    title: 'Test Concert',
    description: '<p>Amazing show</p>',
    important_info: '<p>Bring ID</p>',
    why_go: ['Great music', 'Awesome venue'],
    url: 'https://tickets.example.com',
    venue_name: 'Rock Hall',
    venue_address: 'Main St 1',
    lat: 59.437,
    lng: 24.753,
    price_min: 15,
    price_max: null,
    currency: 'EUR',
  }),
  language: 'en',
  claim_status: 'unclaimed',
  listed_by: null,
};

describe('EventDetail', () => {
  it('shows loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });

  it('renders event title on success', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
  });

  it('renders why_go bullets', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Great music')).toBeInTheDocument());
  });

  it('renders sanitized description', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Amazing show')).toBeInTheDocument());
  });

  it('renders important_info section', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Bring ID')).toBeInTheDocument());
  });

  it('renders price', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('€15')).toBeInTheDocument());
  });

  it('renders tickets link', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /ticket/i });
      expect(link).toHaveAttribute('href', 'https://tickets.example.com');
    });
  });

  it('calls trackExternalClick on tickets link click', async () => {
    const { trackExternalClick } = await import('../../utils');
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => screen.getByRole('link', { name: /ticket/i }));
    await userEvent.click(screen.getByRole('link', { name: /ticket/i }));
    expect(trackExternalClick).toHaveBeenCalledWith(1);
  });

  it('renders map link when lat/lng present', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => {
      const mapLink = screen.getByRole('link', { name: /map/i });
      expect(mapLink).toHaveAttribute('href', expect.stringContaining('maps'));
    });
  });

  it('renders category and vibe tags as links to Explore filtered by that slug', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => {
      const categoryLink = screen.getByRole('link', { name: /music/i });
      expect(categoryLink).toHaveAttribute('href', '/en/explore?category=music');
    });
    const vibeLink = screen.getByRole('link', { name: /vibrant/i });
    expect(vibeLink).toHaveAttribute('href', '/en/explore?vibe=vibrant');
  });

  it('back button calls navigate(-1)', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => screen.getByRole('button', { name: /back/i }));
    await userEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(mockNavigate).toHaveBeenCalledWith(-1);
  });

  async function openOverflowMenu() {
    const trigger = await screen.findByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
  }

  it('renders share and report menu items when authenticated', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await openOverflowMenu();
    expect(screen.getByRole('menuitem', { name: 'Share' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Report event' })).toBeInTheDocument();
  });

  it('does not copy or toast when user cancels the native share sheet', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const share = vi.fn().mockRejectedValue(new DOMException('cancelled', 'AbortError'));
    Object.assign(navigator, { clipboard: { writeText }, share });
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await openOverflowMenu();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Share' }));
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(writeText).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    delete (navigator as { share?: unknown }).share;
  });

  it('copies link and shows toast when navigator.share is unavailable', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await openOverflowMenu();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Share' }));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Link copied'));
  });

  it('opens the report modal when Report event is clicked while authenticated', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await openOverflowMenu();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Report event' }));
    expect(screen.getByRole('dialog', { name: 'Report event' })).toBeInTheDocument();
  });

  it('shows a disabled Reported row when the event was already reported', async () => {
    mockGet.mockResolvedValueOnce({ ...eventData, reported: true });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await openOverflowMenu();
    expect(screen.getByRole('menuitem', { name: 'Reported' })).toBeDisabled();
  });

  it('renders feedback buttons when authenticated', async () => {
    mockIsAuthenticated.mockReturnValue(true);
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Like' })).toBeInTheDocument());
  });

  describe('logged out', () => {
    beforeEach(() => {
      mockIsAuthenticated.mockReturnValue(false);
    });
    afterEach(() => {
      mockIsAuthenticated.mockReturnValue(true);
    });

    it('renders event content with no redirect and no feedback buttons', async () => {
      mockGet.mockResolvedValueOnce(eventData);
      renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
      await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
      expect(screen.queryByRole('button', { name: 'Like' })).not.toBeInTheDocument();
    });

    it('renders share menu item even when signed out', async () => {
      mockGet.mockResolvedValueOnce(eventData);
      renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
      await openOverflowMenu();
      expect(screen.getByRole('menuitem', { name: 'Share' })).toBeInTheDocument();
    });

    it('redirects to /login when Report event is clicked while signed out', async () => {
      mockGet.mockResolvedValueOnce(eventData);
      renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
      await openOverflowMenu();
      await userEvent.click(screen.getByRole('menuitem', { name: 'Report event' }));
      expect(mockNavigate).toHaveBeenCalledWith('/en/login', undefined);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('switching locale does not call api.patch', async () => {
      mockGet.mockResolvedValueOnce(eventData);
      renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
      await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
      const localeButton = screen.getByRole('button', { name: 'EN' });
      await userEvent.click(localeButton);
      const etOption = await screen.findByText('ET');
      await userEvent.click(etOption);
      expect(api.patch).not.toHaveBeenCalled();
    });

    it('clicking tickets link does not call trackExternalClick (avoids 401 redirect)', async () => {
      const { trackExternalClick } = await import('../../utils');
      mockGet.mockResolvedValueOnce(eventData);
      renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
      await waitFor(() => screen.getByRole('link', { name: /ticket/i }));
      await userEvent.click(screen.getByRole('link', { name: /ticket/i }));
      expect(trackExternalClick).not.toHaveBeenCalled();
    });
  });
});

describe('EventDetail claim discovery (#414)', () => {
  const mockOrganizerPost = vi.mocked(organizerApi.post);
  const mockOrganizerGet = vi.mocked(organizerApi.get);

  afterEach(() => {
    localStorage.removeItem(ORGANIZER_SIGNED_IN_HINT_KEY);
    mockOrganizerPost.mockReset();
    mockOrganizerGet.mockReset();
  });

  it('shows the claim panel for an unclaimed event, no pill', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Is this your event?')).toBeInTheDocument());
    expect(screen.queryByText(/pending review|verified/i)).not.toBeInTheDocument();
  });

  it('hides the pending pill from a non-organizer viewer, but still shows the claim panel (#441, #451)', async () => {
    // (#451) The public payload never actually carries "pending" any more
    // (the backend collapses it into "unclaimed") — this asserts the
    // frontend's own defense-in-depth: a non-organizer viewer never even
    // queries the organizer-scoped for-event lookup that could reveal it.
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'unclaimed' });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
    expect(screen.queryByText('Claim pending review')).not.toBeInTheDocument();
    expect(screen.getByText('Is this your event?')).toBeInTheDocument();
    expect(mockOrganizerGet).not.toHaveBeenCalled();
  });

  it('shows the pending pill and the claim panel to the owning organizer (#451)', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'unclaimed' });
    mockOrganizerGet.mockResolvedValueOnce({ claim: { status: 'pending' } });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Claim pending review')).toBeInTheDocument());
    expect(screen.getByText('Is this your event?')).toBeInTheDocument();
  });

  it('hides the pending pill from a rival organizer even when signed in (#451)', async () => {
    // The bug this closes: any signed-in organizer used to see a rival's
    // pending pill. Now the for-event lookup returns null for a caller who
    // isn't the claimant, so no pill renders.
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'unclaimed' });
    mockOrganizerGet.mockResolvedValueOnce({ claim: null });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Is this your event?')).toBeInTheDocument());
    expect(screen.queryByText('Claim pending review')).not.toBeInTheDocument();
  });

  it('shows a pill and no panel once a claim is granted', async () => {
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'claimed' });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Organizer-verified')).toBeInTheDocument());
    expect(screen.queryByText('Is this your event?')).not.toBeInTheDocument();
  });

  it('shows the "Listed by X" credit for a claimed event with an organizer name', async () => {
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'claimed', listed_by: 'Tallinn Jazz Club' });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Listed by Tallinn Jazz Club')).toBeInTheDocument());
  });

  it('omits the "Listed by X" credit when the organizer has no name set', async () => {
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'claimed', listed_by: null });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Organizer-verified')).toBeInTheDocument());
    expect(screen.queryByText(/^Listed by/)).not.toBeInTheDocument();
  });

  it('shows no claim CTA or pill for a not-claimable direct submission (#445)', async () => {
    mockGet.mockResolvedValueOnce({ ...eventData, claim_status: 'not_claimable' });
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
    expect(screen.queryByText('Is this your event?')).not.toBeInTheDocument();
    expect(screen.queryByText(/pending review|verified/i)).not.toBeInTheDocument();
  });

  it('a signed-out visitor gets the email-capture form, not a direct claim', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Is this your event?')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));
    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument();
    expect(mockOrganizerPost).not.toHaveBeenCalled();
  });

  it('navigates a signed-in organizer to the pending screen after claiming (#415)', async () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    mockOrganizerPost.mockResolvedValueOnce({ id: 99, status: 'pending' });
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/en/events/1', pathPattern: '/:locale/events/:id' });
    await waitFor(() => expect(screen.getByText('Is this your event?')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));
    expect(mockOrganizerPost).toHaveBeenCalledWith('/organizer/claims', { event_id: 1 });
    // react-router-dom is mocked file-wide (above) so useNavigate resolves to
    // this spy rather than performing a real route change.
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/en/organizer/claims/99/pending', undefined));
  });
});
