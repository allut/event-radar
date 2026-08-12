import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useLocaleMutation } from './useLocaleMutation';
import { makeQueryWrapper } from '../test/utils';
import { setSignedInHint, clearSignedInHint, getLocale } from '../lib/auth';

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
  const { wrapper } = makeQueryWrapper();
  return { wrapper };
}

describe('useLocaleMutation', () => {
  it('authenticated: PATCHes, persists locale, fires onSuccess', async () => {
    setSignedInHint();
    const onSuccess = vi.fn();
    const { wrapper } = makeWrapper();
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
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useLocaleMutation({ onError }), { wrapper });

    act(() => result.current.handleLocaleChange('ru'));

    await waitFor(() => expect(onError).toHaveBeenCalled());
    // reverted to the stored locale (default), not the optimistic 'ru'
    expect(result.current.locale).toBe(getLocale());
  });

  it('anonymous: persists locally, no PATCH, still fires onSuccess', async () => {
    clearSignedInHint();
    const onSuccess = vi.fn();
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useLocaleMutation({ onSuccess }), { wrapper });

    act(() => result.current.handleLocaleChange('et'));

    expect(mockPatch).not.toHaveBeenCalled();
    expect(getLocale()).toBe('et');
    expect(onSuccess).toHaveBeenCalled();
  });
});
