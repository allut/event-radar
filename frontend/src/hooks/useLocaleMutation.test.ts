import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useLocaleMutation } from './useLocaleMutation';
import { makeQueryWrapper } from '../test/utils';
import { setToken, clearToken, getLocale } from '../lib/auth';

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

function makeWrapper() {
  const { wrapper, queryClient } = makeQueryWrapper();
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
  return { wrapper, invalidateSpy };
}

describe('useLocaleMutation', () => {
  it('authenticated: PATCHes, persists locale, invalidates, fires onSuccess', async () => {
    setToken('tok');
    const onSuccess = vi.fn();
    const { wrapper, invalidateSpy } = makeWrapper();
    const { result } = renderHook(
      () => useLocaleMutation(['feed'], { onSuccess }),
      { wrapper },
    );

    act(() => result.current.handleLocaleChange('en'));

    expect(result.current.locale).toBe('en');
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(mockPatch).toHaveBeenCalledWith('/users/me', { locale: 'en' });
    expect(getLocale()).toBe('en');
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['feed'] });
  });

  it('authenticated error: reverts to stored locale and fires onError', async () => {
    setToken('tok');
    mockPatch.mockRejectedValueOnce(new Error('network'));
    const onError = vi.fn();
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useLocaleMutation(['feed'], { onError }),
      { wrapper },
    );

    act(() => result.current.handleLocaleChange('ru'));

    await waitFor(() => expect(onError).toHaveBeenCalled());
    // reverted to the stored locale (default), not the optimistic 'ru'
    expect(result.current.locale).toBe(getLocale());
  });

  it('anonymous: persists locally, no PATCH, still invalidates + onSuccess', async () => {
    clearToken();
    const onSuccess = vi.fn();
    const { wrapper, invalidateSpy } = makeWrapper();
    const { result } = renderHook(
      () => useLocaleMutation(['event'], { onSuccess }),
      { wrapper },
    );

    act(() => result.current.handleLocaleChange('et'));

    expect(mockPatch).not.toHaveBeenCalled();
    expect(getLocale()).toBe('et');
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['event'] });
    expect(onSuccess).toHaveBeenCalled();
  });
});
