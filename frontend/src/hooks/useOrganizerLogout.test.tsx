import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useOrganizerLogout } from './useOrganizerLogout';
import { makeRouterQueryWrapper } from '../test/utils';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => mockNavigate,
}));

vi.mock('../lib/organizerAuth', () => ({
  beginOrganizerLogout: vi.fn(),
  clearOrganizerSignedInHint: vi.fn(),
}));

vi.mock('../api/client', () => ({
  organizerApi: {
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

import { beginOrganizerLogout, clearOrganizerSignedInHint } from '../lib/organizerAuth';
import { organizerApi } from '../api/client';

describe('useOrganizerLogout', () => {
  const { wrapper } = makeRouterQueryWrapper();

  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(beginOrganizerLogout).mockClear();
    vi.mocked(clearOrganizerSignedInHint).mockClear();
    vi.mocked(organizerApi.post).mockClear();
  });

  it('flags logout, calls the server-side logout endpoint, clears the organizer hint, and navigates to /organizer/login', () => {
    const { result } = renderHook(() => useOrganizerLogout(), { wrapper });
    act(() => result.current());

    expect(beginOrganizerLogout).toHaveBeenCalled();
    expect(organizerApi.post).toHaveBeenCalledWith('/organizer/auth/logout');
    expect(clearOrganizerSignedInHint).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/organizer/login', { replace: true });
  });
});
