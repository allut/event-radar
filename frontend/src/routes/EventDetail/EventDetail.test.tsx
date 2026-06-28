import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventDetail from './EventDetail';
import { renderWithProviders, makeEvent } from '../../test/utils';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
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

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);

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
};

describe('EventDetail', () => {
  it('shows loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('network'));
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });

  it('renders event title on success', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText('Test Concert')).toBeInTheDocument());
  });

  it('renders why_go bullets', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText('Great music')).toBeInTheDocument());
  });

  it('renders sanitized description', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText('Amazing show')).toBeInTheDocument());
  });

  it('renders important_info section', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText('Bring ID')).toBeInTheDocument());
  });

  it('renders price', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => expect(screen.getByText('€15')).toBeInTheDocument());
  });

  it('renders tickets link', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /ticket/i });
      expect(link).toHaveAttribute('href', 'https://tickets.example.com');
    });
  });

  it('calls trackExternalClick on tickets link click', async () => {
    const { trackExternalClick } = await import('../../utils');
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => screen.getByRole('link', { name: /ticket/i }));
    await userEvent.click(screen.getByRole('link', { name: /ticket/i }));
    expect(trackExternalClick).toHaveBeenCalledWith(1);
  });

  it('renders map link when lat/lng present', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => {
      const mapLink = screen.getByRole('link', { name: /map/i });
      expect(mapLink).toHaveAttribute('href', expect.stringContaining('maps'));
    });
  });

  it('back button calls navigate(-1)', async () => {
    mockGet.mockResolvedValueOnce(eventData);
    renderWithProviders(<EventDetail />, { route: '/events/1', pathPattern: '/events/:id' });
    await waitFor(() => screen.getByRole('button', { name: /back/i }));
    await userEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(mockNavigate).toHaveBeenCalledWith(-1);
  });
});
