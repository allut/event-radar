import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
  organizerApi: { post: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockPost = vi.mocked(organizerApi.post);

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
    const link = screen.getByRole('link', { name: /back to event radar/i });
    expect(link).toHaveAttribute('href', '/');
  });

  it('does not render the Google button when the flag is off', () => {
    renderWithProviders(<OrganizerLogin />);
    expect(screen.queryByRole('link', { name: /sign in with google/i })).not.toBeInTheDocument();
  });
});

describe('OrganizerLogin with Google sign-in enabled', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED', 'true');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders the Google button pointing at the organizer start endpoint, email form collapsed', () => {
    renderWithProviders(<OrganizerLogin />);

    const googleLink = screen.getByRole('link', { name: /sign in with google/i });
    expect(googleLink).toHaveAttribute('href', '/api/organizer/auth/google/start');
    expect(screen.queryByRole('textbox', { name: /email/i })).not.toBeInTheDocument();
  });

  it('expands the magic-link form behind the "continue with email" toggle', async () => {
    renderWithProviders(<OrganizerLogin />);

    await userEvent.click(screen.getByRole('button', { name: /continue with email instead/i }));

    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByText('or')).toBeInTheDocument();
  });

  it('shows the cancelled banner for the access_denied error code', () => {
    renderWithProviders(<OrganizerLogin />, { route: '/organizer/login?google_error=access_denied' });

    expect(screen.getByRole('alert')).toHaveTextContent('Sign-in was cancelled.');
  });

  it('shows the generic failed banner for every other error code', () => {
    renderWithProviders(<OrganizerLogin />, { route: '/organizer/login?google_error=state_invalid' });

    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong signing in with google/i);
  });
});
