import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFeedback } from './useFeedback';
import { makeQueryWrapper } from '../test/utils';

vi.mock('../api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
  },
}));

import { api } from '../api/client';
const mockPost = vi.mocked(api.post);
const mockDelete = vi.mocked(api.delete);

function makeWrapper() {
  const { wrapper, queryClient } = makeQueryWrapper();
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
  return { wrapper, invalidateSpy };
}

describe('useFeedback', () => {
  it('happy path: sets activeSignal and calls onChange', async () => {
    const onChange = vi.fn();
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1, { onChange }), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(result.current.activeSignal).toBe('like');
    expect(onChange).toHaveBeenCalled();
  });

  it('invalidates every feedback-dependent query family on success', async () => {
    const { wrapper, invalidateSpy } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('bookmark');
    });

    const invalidatedKeys = invalidateSpy.mock.calls.map((c) => c[0]?.queryKey);
    expect(invalidatedKeys).toEqual(
      expect.arrayContaining([['saved'], ['feed'], ['explore'], ['event']]),
    );
  });

  it('does not invalidate when the API call fails', async () => {
    mockPost.mockRejectedValueOnce(new Error('network'));
    const { wrapper, invalidateSpy } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it('seeds activeSignal from initialSignal', () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1, { initialSignal: 'bookmark' }), { wrapper });
    expect(result.current.activeSignal).toBe('bookmark');
  });

  it('pending resets to false after send', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('bookmark');
    });

    expect(result.current.pending).toBe(false);
  });

  it('ignores when eventId is not yet loaded (undefined)', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(undefined), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(mockPost).not.toHaveBeenCalled();
    expect(result.current.activeSignal).toBeNull();
  });

  it('sends feedback for event id 0 (numeric truthiness must not gate a real id)', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(0), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(mockPost).toHaveBeenCalled();
    expect(result.current.activeSignal).toBe('like');
  });

  it('pressing the active signal again unchecks it via DELETE', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => { await result.current.sendFeedback('like'); });
    expect(result.current.activeSignal).toBe('like');

    await act(async () => { await result.current.sendFeedback('like'); });

    expect(mockDelete).toHaveBeenCalledWith('/feedback/1');
    expect(result.current.activeSignal).toBeNull();
  });

  it('pressing a different signal switches (POST), not DELETE', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => { await result.current.sendFeedback('like'); });
    mockPost.mockClear();

    await act(async () => { await result.current.sendFeedback('dislike'); });

    expect(mockPost).toHaveBeenCalledWith('/feedback', { event_id: 1, signal: 'dislike' });
    expect(mockDelete).not.toHaveBeenCalled();
    expect(result.current.activeSignal).toBe('dislike');
  });

  it('ignores when pending', async () => {
    let resolveFn!: () => void;
    mockPost.mockImplementationOnce(
      () => new Promise<undefined>((res) => { resolveFn = () => res(undefined); }),
    );

    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    act(() => { void result.current.sendFeedback('like'); });
    expect(result.current.pending).toBe(true);

    await act(async () => { await result.current.sendFeedback('dislike'); });
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolveFn();
  });

  it('swallows API error, pending resets, activeSignal unchanged', async () => {
    mockPost.mockRejectedValueOnce(new Error('network'));

    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('dislike');
    });

    expect(result.current.activeSignal).toBeNull();
    expect(result.current.pending).toBe(false);
  });

  it('patches my_signal into cached feed/explore/event payloads without refetching Explore', async () => {
    const { wrapper, queryClient } = makeQueryWrapper();
    queryClient.setQueryData(['feed', 'et'], { events: [{ id: 1, my_signal: null }, { id: 2, my_signal: null }] });
    // Explore caches one page per query (spec #551), keyed by its page.
    queryClient.setQueryData(['explore', 'et', {}, 2], {
      events: [{ id: 2, my_signal: null }, { id: 1, my_signal: null }],
      total: 30,
      offset: 24,
    });
    queryClient.setQueryData(['event', '1', 'et'], { id: 1, my_signal: null });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(queryClient.getQueryData(['feed', 'et'])).toEqual({
      events: [{ id: 1, my_signal: 'like' }, { id: 2, my_signal: null }],
    });
    expect(queryClient.getQueryData(['explore', 'et', {}, 2])).toEqual({
      events: [{ id: 2, my_signal: null }, { id: 1, my_signal: 'like' }],
      total: 30,
      offset: 24,
    });
    expect(queryClient.getQueryData(['event', '1', 'et'])).toEqual({ id: 1, my_signal: 'like' });
    const byKey = Object.fromEntries(invalidateSpy.mock.calls.map((c) => [String(c[0]?.queryKey), c[0]?.refetchType]));
    expect(byKey.saved).toBeUndefined();
    expect(byKey.feed).toBeUndefined();
    expect(byKey.explore).toBe('none');
    expect(byKey.event).toBe('none');
  });

  it('refetches active Explore on a dislike, since the server hard-excludes the event', async () => {
    const { wrapper, queryClient } = makeQueryWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useFeedback(1), { wrapper });

    await act(async () => {
      await result.current.sendFeedback('dislike');
    });

    const explore = invalidateSpy.mock.calls.find((c) => c[0]?.queryKey?.[0] === 'explore');
    expect(explore?.[0]?.refetchType).toBe('active');
  });
});
