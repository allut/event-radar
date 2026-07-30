import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrganizerLogin from './OrganizerLogin';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { post: vi.fn() },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('OrganizerLogin', () => {
  it('renders email input and submit button', () => {
    renderWithProviders(<OrganizerLogin />);
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('submits to the organizer request-link endpoint', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<OrganizerLogin />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'organizer@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/organizer/auth/request-link', { email: 'organizer@example.com', locale: 'en' }),
    );
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Invalid email'));
    renderWithProviders(<OrganizerLogin />);
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'bad@test.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Invalid email')).toBeInTheDocument();
  });

  it('renders a back-to-site link pointing to /', () => {
    renderWithProviders(<OrganizerLogin />);
    const link = screen.getByRole('link', { name: /back to what's on radar/i });
    expect(link).toHaveAttribute('href', '/');
  });
});
