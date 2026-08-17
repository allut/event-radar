import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { StatusCodes } from 'http-status-codes';
import { useContactSubmit } from './useContactSubmit';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { post: vi.fn() },
}));

import { api, ApiError } from '../api/client';
const mockPost = vi.mocked(api.post);

beforeEach(() => {
  mockPost.mockReset();
});

function fillValidForm(result: { current: ReturnType<typeof useContactSubmit> }) {
  act(() => {
    result.current.setName('Jane');
    result.current.setEmail('jane@example.com');
    result.current.setMessage('Hello there');
  });
}

describe('useContactSubmit', () => {
  it('posts name, email, message, and the honeypot field on submit', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useContactSubmit('en'));
    fillValidForm(result);

    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    expect(mockPost).toHaveBeenCalledWith('/contact', {
      name: 'Jane',
      email: 'jane@example.com',
      message: 'Hello there',
      website: '',
    });
    expect(result.current.state).toBe('success');
  });

  it('trims name/email/message but leaves an untouched honeypot value intact', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useContactSubmit('en'));
    act(() => {
      result.current.setName('  Jane  ');
      result.current.setEmail('  jane@example.com  ');
      result.current.setMessage('  Hello there  ');
      result.current.setWebsite('honeypot-value');
    });

    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    expect(mockPost).toHaveBeenCalledWith('/contact', {
      name: 'Jane',
      email: 'jane@example.com',
      message: 'Hello there',
      website: 'honeypot-value',
    });
  });

  it('does not submit when name, email, or message is blank', async () => {
    const { result } = renderHook(() => useContactSubmit('en'));
    act(() => {
      result.current.setName('Jane');
      result.current.setEmail('jane@example.com');
      // message left blank
    });

    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    expect(mockPost).not.toHaveBeenCalled();
    expect(result.current.state).toBe('idle');
  });

  it('surfaces the ApiError message on failure', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(StatusCodes.BAD_REQUEST, 'Bad request'));
    const { result } = renderHook(() => useContactSubmit('en'));
    fillValidForm(result);

    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(result.current.state).toBe('error'));
    expect(result.current.errorMsg).toBe('Bad request');
  });

  it('falls back to a generic error message for non-ApiError failures', async () => {
    mockPost.mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useContactSubmit('en'));
    fillValidForm(result);

    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });

    await waitFor(() => expect(result.current.state).toBe('error'));
    expect(result.current.errorMsg.length).toBeGreaterThan(0);
    expect(result.current.errorMsg).not.toBe('network down');
  });

  it('reset() clears all fields and returns to idle', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useContactSubmit('en'));
    fillValidForm(result);
    await act(async () => {
      await result.current.submit({ preventDefault: () => {} } as React.FormEvent);
    });
    await waitFor(() => expect(result.current.state).toBe('success'));

    act(() => result.current.reset());

    expect(result.current.state).toBe('idle');
    expect(result.current.name).toBe('');
    expect(result.current.email).toBe('');
    expect(result.current.message).toBe('');
    expect(result.current.errorMsg).toBe('');
  });
});
