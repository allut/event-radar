import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SavedEvents from './SavedEvents';
import { renderWithProviders, makeEvent } from '../../test/utils';
import type { EventData } from '../../components/EventCard';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearToken: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event }: { event: { title: string } }) => <div data-testid="event-card">{event.title}</div>,
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);

interface SavedEventsResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

function savedResponse(
  events: EventData[],
  opts: Partial<Pick<SavedEventsResponse, 'total' | 'offset' | 'has_more'>> = {},
): SavedEventsResponse {
  return {
    events,
    total: opts.total ?? events.length,
    limit: 24,
    offset: opts.offset ?? 0,
    has_more: opts.has_more ?? false,
  };
}

beforeEach(() => {
  mockGet.mockReset();
});

describe('SavedEvents', () => {
  it('renders bookmarked events by default', async () => {
    mockGet.mockImplementation((path: string) => {
      expect(path).toContain('signal=bookmark');
      return Promise.resolve(savedResponse([makeEvent({ id: 1, title: 'Jazz Night' })]));
    });

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(1));
    expect(screen.getByText('Jazz Night')).toBeInTheDocument();
  });

  it('switching tabs refetches with the new signal', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path.includes('signal=like')) {
        return Promise.resolve(savedResponse([makeEvent({ id: 2, title: 'Liked Show' })]));
      }
      return Promise.resolve(savedResponse([makeEvent({ id: 1, title: 'Jazz Night' })]));
    });

    renderWithProviders(<SavedEvents />, { route: '/saved' });
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Liked/ }));

    await waitFor(() => expect(screen.getByText('Liked Show')).toBeInTheDocument());
  });

  it('shows empty state when no events match', async () => {
    mockGet.mockResolvedValue(savedResponse([]));

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() => expect(screen.getByText('Nothing here yet')).toBeInTheDocument());
  });

  it('shows error state on failure', async () => {
    mockGet.mockRejectedValue(new Error('network'));

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() =>
      expect(screen.getByText('Failed to load saved events. Please refresh.')).toBeInTheDocument(),
    );
  });

  it('shows Load more when has_more is true', async () => {
    mockGet.mockResolvedValue(savedResponse([makeEvent({ id: 1 })], { has_more: true, total: 2 }));

    renderWithProviders(<SavedEvents />, { route: '/saved' });

    await waitFor(() => expect(screen.getByText('Load more')).toBeInTheDocument());
  });
});
