import { type ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { type EventData } from '../components/EventCard';

interface RenderOptions {
  route?: string;
  pathPattern?: string;
}

export function renderWithProviders(ui: ReactNode, { route = '/', pathPattern }: RenderOptions = {}): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        {pathPattern ? (
          <Routes>
            <Route path={pathPattern} element={ui} />
          </Routes>
        ) : (
          ui
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function makeEvent(overrides: Partial<EventData> = {}): EventData {
  return {
    id: 1,
    slug: 'test-event',
    title: 'Test Event',
    description: null,
    important_info: null,
    starts_at: '2024-07-15T18:00:00Z',
    ends_at: null,
    venue_name: 'Test Venue',
    venue_address: 'Test Street 1',
    lat: 59.437,
    lng: 24.753,
    url: 'https://example.com/tickets',
    image_url: null,
    price_min: null,
    price_max: null,
    currency: null,
    categories: ['music'],
    vibes: ['vibrant'],
    why_go: [],
    quality_score: 0.8,
    ...overrides,
  };
}
