import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, renderHook, act, waitFor } from '@testing-library/react';
import { useLocaleMutation } from './useLocaleMutation';
import { setSignedInHint, clearSignedInHint, getLocale, getStoredLocale } from '../lib/auth';
import { makeRouterQueryWrapper } from '../test/utils';

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
// handleLocaleChange resolves against a realistic route table. Also mounts
// LocationProbe so tests can assert the router location a navigate() lands on.
function makeWrapper(initialPath: string, bareChildPath: string) {
  return makeRouterQueryWrapper({
    initialPath,
    routePatterns: [bareChildPath, `/:locale${bareChildPath}`],
    withLocationProbe: true,
  });
}

describe('useLocaleMutation', () => {
  it('authenticated: persists locale before navigating (synchronously, ahead of the PATCH), PATCHes, fires onSuccess', async () => {
    setSignedInHint();
    const onSuccess = vi.fn();
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation({ onSuccess }), { wrapper });

    act(() => result.current.handleLocaleChange('en'));

    // Persisted synchronously — before the PATCH promise has any chance to
    // settle — since BareLocaleGate reads storage in the same render the
    // navigate below triggers.
    expect(result.current.locale).toBe('en');
    expect(getStoredLocale()).toBe('en');
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/settings');

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(mockPatch).toHaveBeenCalledWith('/users/me', { locale: 'en' });
    expect(getLocale()).toBe('en');
  });

  it('switching to Estonian lands on the bare path (no bounce)', async () => {
    setSignedInHint();
    const { wrapper } = makeWrapper('/ru/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    act(() => result.current.handleLocaleChange('et'));

    expect(getStoredLocale()).toBe('et');
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/settings');
    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
  });

  it('preserves the query string when switching locale', async () => {
    setSignedInHint();
    const { wrapper } = makeWrapper('/explore?category=music', '/explore');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    act(() => result.current.handleLocaleChange('ru'));

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/ru/explore?category=music');
    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
  });

  it('authenticated error: reverts state, storage, and URL together, and fires onError', async () => {
    setSignedInHint();
    mockPatch.mockRejectedValueOnce(new Error('network'));
    const onError = vi.fn();
    const { wrapper } = makeWrapper('/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation({ onError }), { wrapper });

    act(() => result.current.handleLocaleChange('ru'));
    expect(getStoredLocale()).toBe('ru');

    await waitFor(() => expect(onError).toHaveBeenCalled());
    // reverted to the prior state, storage, and URL together — none was
    // stored before the switch, so storage reverts to "no preference" (null)
    expect(result.current.locale).toBe('et');
    expect(getStoredLocale()).toBeNull();
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/settings');
  });

  it('authenticated error with a prior stored preference reverts storage to it, not to null', async () => {
    setSignedInHint();
    localStorage.setItem('locale', 'en');
    mockPatch.mockRejectedValueOnce(new Error('network'));
    const { wrapper } = makeWrapper('/en/settings', '/settings');
    const { result } = renderHook(() => useLocaleMutation(), { wrapper });

    act(() => result.current.handleLocaleChange('ru'));
    await waitFor(() => expect(result.current.locale).toBe('en'));

    expect(getStoredLocale()).toBe('en');
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/en/settings');
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
