import { t } from '../../i18n';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
  it('renders the Dial brand mark in the header', () => {
    renderWithProviders(<Login />, { route: '/en/login' });
    expect(screen.getByRole('banner').querySelector('svg')).not.toBeNull();
    expect(screen.queryByText('◉')).not.toBeInTheDocument();
  });

  it('renders email input and submit button', () => {
    renderWithProviders(<Login />, { route: '/en/login' });
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('submits email and shows success view', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />, { route: '/en/login' });
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'user@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    expect(screen.getByText(/user@example.com/)).toBeInTheDocument();
  });

  it('calls api.post with correct path and lowercased email', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />, { route: '/en/login' });
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'User@Example.COM');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/auth/request-link', { email: 'user@example.com', locale: 'en' }));
  });

  it('shows error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Invalid email'));
    renderWithProviders(<Login />, { route: '/en/login' });
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'bad@test.example');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Invalid email')).toBeInTheDocument();
  });

  it('renders a Terms of Service link pointing to /terms', () => {
    renderWithProviders(<Login />, { route: '/en/login' });
    const link = screen.getByRole('link', { name: /terms of service/i });
    expect(link).toHaveAttribute('href', '/en/terms');
  });

  it('"use different" button resets to idle form', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Login />, { route: '/en/login' });
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'a@b.example');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => screen.getByRole('status'));
    await userEvent.click(screen.getByRole('button', { name: /different/i }));
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
  });

  it('renders an organizer entry link pointing to /organizer/login', () => {
    renderWithProviders(<Login />, { route: '/en/login' });
    const link = screen.getByRole('link', { name: /organizing an event/i });
    expect(link).toHaveAttribute('href', '/en/organizer/login');
  });

  it('does not render the Google button when the flag is off', () => {
    renderWithProviders(<Login />, { route: '/en/login' });
    expect(screen.queryByRole('link', { name: /sign in with google/i })).not.toBeInTheDocument();
  });
});

describe('Login with Google sign-in enabled', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED', 'true');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders the Google button pointing at the consumer start endpoint, email form collapsed', () => {
    renderWithProviders(<Login />, { route: '/en/login' });

    const googleLink = screen.getByRole('link', { name: /sign in with google/i });
    expect(googleLink).toHaveAttribute('href', '/api/auth/google/start');
    expect(screen.queryByRole('textbox', { name: /email/i })).not.toBeInTheDocument();
  });

  it('expands the magic-link form behind the "continue with email" toggle', async () => {
    renderWithProviders(<Login />, { route: '/en/login' });

    await userEvent.click(screen.getByRole('button', { name: /continue with email instead/i }));

    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByText('or')).toBeInTheDocument();
  });

  it('shows the cancelled banner for the access_denied error code', () => {
    renderWithProviders(<Login />, { route: '/en/login?google_error=access_denied' });

    expect(screen.getByRole('alert')).toHaveTextContent('Sign-in was cancelled.');
  });

  it('shows the generic failed banner for every other error code', () => {
    renderWithProviders(<Login />, { route: '/en/login?google_error=state_invalid' });

    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong signing in with google/i);
  });
});

describe('Login locale', () => {
  // The page speaks the URL's language (like the Footer under it, #497) —
  // never the saved preference, mocked to 'en' above.
  it('renders in the URL prefix\'s language', () => {
    renderWithProviders(<Login />, { route: '/ru/login' });
    expect(screen.getAllByText(t('tagline', 'ru')).length).toBeGreaterThan(0);
  });

  it('renders Estonian on a bare path', () => {
    renderWithProviders(<Login />, { route: '/login' });
    expect(screen.getAllByText(t('tagline', 'et')).length).toBeGreaterThan(0);
  });
});
