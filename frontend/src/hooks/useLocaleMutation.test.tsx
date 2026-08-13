import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { useLocaleMutation } from './useLocaleMutation';
import { setSignedInHint, clearSignedInHint, getLocale, getStoredLocale } from '../lib/auth';

vi.mock('../api/client', () => ({
  api: { patch: vi.fn().mockResolvedValue(undefined) },
}));

import { api } from '../api/client';
const mockPatch = vi.mocked(api.patch);

beforeEach(() => {
  localStorage.clear();
  mockPatch.mockReset();
  mockPatch.mockResolvedValue(undefined);
});

// Mounts the hook behind a bare route and its locale-prefixed sibling —
// mirrors App.tsx's dual route registration, so navigate() from
// handleLocaleChange resolves against a realistic route table.
function makeWrapper(initialPath: string, bareChildPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route path={bareChildPath} element={<>{children}</>} />
            <Route path={`/:locale${bareChildPath}`} element={<>{children}</>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }
  return { wrapper: Wrapper };
}

describe('useLocaleMutation', () => {
  it('authenticated: navigates, PATCHes, persists locale, fires onSuccess', async () => {
    setSignedInHint();
    const onSuccess = vi.fn();
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation({ onSuccess }), { wrapper });

    act(() => result.current.handleLocaleChange('en'));

    expect(result.current.locale).toBe('en');
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(mockPatch).toHaveBeenCalledWith('/users/me', { locale: 'en' });
    expect(getLocale()).toBe('en');
  });

  it('authenticated error: reverts to stored locale and fires onError', async () => {
    setSignedInHint();
    mockPatch.mockRejectedValueOnce(new Error('network'));
    const onError = vi.fn();
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation({ onError }), { wrapper });

    act(() => result.current.handleLocaleChange('ru'));

    await waitFor(() => expect(onError).toHaveBeenCalled());
    // reverted to the stored preference (Estonian, since none was set), not
    // the optimistic 'ru'
    expect(result.current.locale).toBe(getStoredLocale() ?? 'et');
  });

  it('anonymous: persists locally, no PATCH, still fires onSuccess', async () => {
    clearSignedInHint();
    const onSuccess = vi.fn();
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation({ onSuccess }), { wrapper });

    act(() => result.current.handleLocaleChange('et'));

    expect(mockPatch).not.toHaveBeenCalled();
    expect(getLocale()).toBe('et');
    expect(onSuccess).toHaveBeenCalled();
  });

  it('resolves locale from an explicit URL segment over the stored preference', () => {
    localStorage.setItem('locale', 'en');
    const { wrapper } = makeWrapper('/ru/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    expect(result.current.locale).toBe('ru');
  });

  it('falls back to Estonian for an unrecognized URL locale segment', () => {
    const { wrapper } = makeWrapper('/xx/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    expect(result.current.locale).toBe('et');
  });

  it('publicRoute callers default to Estonian on a bare path, ignoring stored preference', () => {
    localStorage.setItem('locale', 'en');
    const { wrapper } = makeWrapper('/', '/');
    const { result } = renderHook(() => useLocaleMutation({ publicRoute: true }), { wrapper });

    expect(result.current.locale).toBe('et');
  });

  it('non-public callers on a bare path with no stored preference default to Estonian, not getLocale()\'s en fallback', () => {
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    expect(result.current.locale).toBe('et');
  });
});
