import { describe, it, expect, vi, beforeEach } from 'vitest';
import { type ReactNode } from 'react';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useLogout } from './useLogout';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => mockNavigate,
}));

vi.mock('../lib/auth', () => ({
  beginLogout: vi.fn(),
  clearSignedInHint: vi.fn(),
}));

vi.mock('../api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

import { beginLogout, clearSignedInHint } from '../lib/auth';
import { api } from '../api/client';

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('useLogout', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(beginLogout).mockClear();
    vi.mocked(clearSignedInHint).mockClear();
    vi.mocked(api.post).mockClear();
  });

  it('flags logout, calls the server-side logout endpoint, clears the signed-in hint, and navigates to /', () => {
    const { result } = renderHook(() => useLogout(), { wrapper });
    act(() => result.current());

    expect(beginLogout).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith('/auth/logout');
    expect(clearSignedInHint).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });
});
