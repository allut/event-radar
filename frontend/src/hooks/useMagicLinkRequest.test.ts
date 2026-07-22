import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMagicLinkRequest } from './useMagicLinkRequest';
import { ApiError } from '../api/client';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, api: { post: vi.fn().mockResolvedValue(undefined) } };
});

import { api } from '../api/client';
const mockPost = vi.mocked(api.post);

const noSubmit = { preventDefault: () => {} } as React.FormEvent;

beforeEach(() => {
  mockPost.mockReset();
  mockPost.mockResolvedValue(undefined);
});

describe('useMagicLinkRequest', () => {
  it('empty email is a no-op', async () => {
    const { result } = renderHook(() => useMagicLinkRequest('en'));
    await act(async () => { await result.current.submit(noSubmit); });
    expect(mockPost).not.toHaveBeenCalled();
    expect(result.current.state).toBe('idle');
  });

  it('success: lowercases + trims email, moves to success', async () => {
    const { result } = renderHook(() => useMagicLinkRequest('en'));
    act(() => result.current.setEmail('  User@Example.COM '));
    await act(async () => { await result.current.submit(noSubmit); });

    expect(mockPost).toHaveBeenCalledWith('/auth/request-link', { email: 'user@example.com', locale: 'en' });
    expect(result.current.state).toBe('success');
  });

  it('ApiError sets errorMsg from the error message and state=error', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests'));
    const { result } = renderHook(() => useMagicLinkRequest('en'));
    act(() => result.current.setEmail('a@b.co'));
    await act(async () => { await result.current.submit(noSubmit); });

    expect(result.current.state).toBe('error');
    expect(result.current.errorMsg).toBe('Too many requests');
  });

  it('non-ApiError falls back to generic error text', async () => {
    mockPost.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useMagicLinkRequest('en'));
    act(() => result.current.setEmail('a@b.co'));
    await act(async () => { await result.current.submit(noSubmit); });

    expect(result.current.state).toBe('error');
    expect(result.current.errorMsg).not.toBe('boom');
    expect(result.current.errorMsg.length).toBeGreaterThan(0);
  });

  it('reset returns to idle and clears email', async () => {
    const { result } = renderHook(() => useMagicLinkRequest('en'));
    act(() => result.current.setEmail('a@b.co'));
    await act(async () => { await result.current.submit(noSubmit); });
    act(() => result.current.reset());

    expect(result.current.state).toBe('idle');
    expect(result.current.email).toBe('');
    expect(result.current.errorMsg).toBe('');
  });
});
