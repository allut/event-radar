import { describe, it, expect, vi, beforeEach } from 'vitest';
import { type ReactNode } from 'react';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useOrganizerLogout } from './useOrganizerLogout';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => mockNavigate,
}));

vi.mock('../lib/organizerAuth', () => ({
  beginOrganizerLogout: vi.fn(),
  clearOrganizerToken: vi.fn(),
}));

import { beginOrganizerLogout, clearOrganizerToken } from '../lib/organizerAuth';

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('useOrganizerLogout', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(beginOrganizerLogout).mockClear();
    vi.mocked(clearOrganizerToken).mockClear();
  });

  it('flags logout, clears the organizer token, and navigates to /organizer/login', () => {
    const { result } = renderHook(() => useOrganizerLogout(), { wrapper });
    act(() => result.current());

    expect(beginOrganizerLogout).toHaveBeenCalled();
    expect(clearOrganizerToken).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/organizer/login', { replace: true });
  });
});
