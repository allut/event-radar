import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFeedback } from './useFeedback';

vi.mock('../api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue(undefined),
  },
}));

import { api } from '../api/client';
const mockPost = vi.mocked(api.post);

describe('useFeedback', () => {
  it('happy path: sets activeSignal and calls onSent', async () => {
    const onSent = vi.fn();
    const { result } = renderHook(() => useFeedback(1, onSent));

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(result.current.activeSignal).toBe('like');
    expect(onSent).toHaveBeenCalled();
  });

  it('pending resets to false after send', async () => {
    const { result } = renderHook(() => useFeedback(1));

    await act(async () => {
      await result.current.sendFeedback('bookmark');
    });

    expect(result.current.pending).toBe(false);
  });

  it('ignores when eventId is falsy (0)', async () => {
    const { result } = renderHook(() => useFeedback(0));

    await act(async () => {
      await result.current.sendFeedback('like');
    });

    expect(mockPost).not.toHaveBeenCalled();
    expect(result.current.activeSignal).toBeNull();
  });

  it('ignores when same signal repeated', async () => {
    const { result } = renderHook(() => useFeedback(1));

    await act(async () => { await result.current.sendFeedback('like'); });
    mockPost.mockClear();

    await act(async () => { await result.current.sendFeedback('like'); });

    expect(mockPost).not.toHaveBeenCalled();
  });

  it('ignores when pending', async () => {
    let resolveFn!: () => void;
    mockPost.mockImplementationOnce(
      () => new Promise<undefined>((res) => { resolveFn = () => res(undefined); }),
    );

    const { result } = renderHook(() => useFeedback(1));

    act(() => { void result.current.sendFeedback('like'); });
    expect(result.current.pending).toBe(true);

    await act(async () => { await result.current.sendFeedback('dislike'); });
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolveFn();
  });

  it('swallows API error, pending resets, activeSignal unchanged', async () => {
    mockPost.mockRejectedValueOnce(new Error('network'));

    const { result } = renderHook(() => useFeedback(1));

    await act(async () => {
      await result.current.sendFeedback('dislike');
    });

    expect(result.current.activeSignal).toBeNull();
    expect(result.current.pending).toBe(false);
  });
});
