import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Login from './Login';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  // Real ApiError (shared class, no network dependency); only api.* stubbed.
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { post: vi.fn() },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('Login', () => {
  it('renders email input and submit button', () => {
    renderWithProviders(<Login />);
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('submits email and shows success view', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'user@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    expect(screen.getByText(/user@example.com/)).toBeInTheDocument();
  });

  it('calls api.post with correct path and lowercased email', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'User@Example.COM');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/auth/request-link', { email: 'user@example.com', locale: 'en' }));
  });

  it('shows error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Invalid email'));
    renderWithProviders(<Login />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'bad@test.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Invalid email')).toBeInTheDocument();
  });

  it('"use different" button resets to idle form', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'a@b.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => screen.getByRole('status'));
    await userEvent.click(screen.getByRole('button', { name: /different/i }));
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
  });
});
