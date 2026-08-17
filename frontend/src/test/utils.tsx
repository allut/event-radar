import { createElement, type ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { HelmetProvider } from 'react-helmet-async';
import { type EventData } from '../components/EventCard';

/** Wrapper for renderHook-based tests that need a QueryClientProvider without a
 * full renderWithProviders() tree (e.g. hook tests with no router dependency). */
export function makeQueryWrapper(): {
  wrapper: ({ children }: { children: ReactNode }) => ReactNode;
  queryClient: QueryClient;
} {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

/** Wrapper for renderHook-based tests that need a MemoryRouter + QueryClientProvider
 * without a full renderWithProviders() tree. Pass `routePatterns` to mount the
 * hook under one or more `<Route>` entries (e.g. a bare path and its locale-prefixed
 * sibling); omit it to mount `children` directly under the router. */
export function makeRouterQueryWrapper({
  initialPath = '/',
  routePatterns,
  queryClient: providedQueryClient,
}: {
  initialPath?: string;
  routePatterns?: string[];
  queryClient?: QueryClient;
} = {}): {
  wrapper: ({ children }: { children: ReactNode }) => ReactNode;
  queryClient: QueryClient;
} {
  const queryClient =
    providedQueryClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialPath]}>
          {routePatterns ? (
            <Routes>
              {routePatterns.map((path) => (
                <Route key={path} path={path} element={<>{children}</>} />
              ))}
            </Routes>
          ) : (
            children
          )}
        </MemoryRouter>
      </QueryClientProvider>
    );
  }
  return { wrapper: Wrapper, queryClient };
}

interface RenderOptions {
  route?: string;
  pathPattern?: string;
  /** Multiple routes (e.g. a route under test plus a redirect target). Takes
   * precedence over `pathPattern`; `ui` is ignored when this is set. */
  routes?: Array<{ path: string; element: ReactNode }>;
  /** Pass a pre-built QueryClient (e.g. to share/inspect it in the test) instead
   * of using the default retry-disabled one. */
  queryClient?: QueryClient;
}

export function renderWithProviders(
  ui: ReactNode,
  { route = '/', pathPattern, routes, queryClient: providedQueryClient }: RenderOptions = {},
): RenderResult {
  const queryClient =
    providedQueryClient ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0, staleTime: 0 },
        mutations: { retry: false },
      },
    });
  return render(
    <HelmetProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          {routes ? (
            <Routes>
              {routes.map(({ path, element }) => (
                <Route key={path} path={path} element={element} />
              ))}
            </Routes>
          ) : pathPattern ? (
            <Routes>
              <Route path={pathPattern} element={ui} />
            </Routes>
          ) : (
            ui
          )}
        </MemoryRouter>
      </QueryClientProvider>
    </HelmetProvider>,
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
    has_free_tier: false,
    categories: ['music'],
    vibes: ['vibrant'],
    why_go: [],
    quality_score: 0.8,
    my_signal: null,
    ...overrides,
  };
}
