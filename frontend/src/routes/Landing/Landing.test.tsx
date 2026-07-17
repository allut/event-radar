import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Landing from './Landing';
import { renderWithProviders, makeEvent } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

vi.mock('../../components/EventCard', () => ({
  default: ({ event, readOnly }: { event: { title: string }; readOnly?: boolean }) => (
    <div data-testid="event-card" data-readonly={String(!!readOnly)}>{event.title}</div>
  ),
}));

vi.mock('../../components/LocaleSelector', () => ({
  default: () => <div data-testid="locale-selector" />,
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);

describe('Landing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ events: [] });
  });

  it('renders the hero headline', async () => {
    renderWithProviders(<Landing />);
    expect(screen.getByRole('heading', { name: /leaving the house/i })).toBeInTheDocument();
  });

  it('renders read-only showcase cards on success', async () => {
    mockGet.mockResolvedValueOnce({
      events: [makeEvent({ id: 1, title: 'Showcase One' }), makeEvent({ id: 2, title: 'Showcase Two' })],
    });
    renderWithProviders(<Landing />);
    await waitFor(() => expect(screen.getAllByTestId('event-card').length).toBe(2));
    expect(screen.getByText('Showcase One')).toBeInTheDocument();
    expect(screen.getAllByTestId('event-card')[0]).toHaveAttribute('data-readonly', 'true');
  });

  it('shows an error message when the showcase fetch fails', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<Landing />);
    await waitFor(() => expect(screen.getByText(/couldn't load events/i)).toBeInTheDocument());
  });

  it('submits the email capture and shows the inbox confirmation', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Landing />);
    const input = screen.getAllByPlaceholderText(/you@example.com/i)[0];
    await userEvent.type(input, 'me@example.com');
    await userEvent.click(screen.getAllByRole('button', { name: /Get Daily 5/i })[0]);
    await waitFor(() => expect(screen.getByText(/Check your inbox/i)).toBeInTheDocument());
    expect(mockPost).toHaveBeenCalledWith('/auth/request-link', { email: 'me@example.com' });
  });
});
