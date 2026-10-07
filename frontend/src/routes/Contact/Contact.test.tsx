import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatusCodes } from 'http-status-codes';
import Contact from './Contact';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/auth')>()),
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  // Real ApiError (shared class, no network dependency); only api.* stubbed.
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from '../../api/client';
const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);

describe('Contact', () => {
  it('links to the FAQ between the intro and the organizer hint', () => {
    renderWithProviders(<Contact />);
    const faq = screen.getByRole('link', { name: 'Quick question? Check the FAQ first →' });
    expect(faq).toHaveAttribute('href', '/faq');
    const intro = screen.getByText(/We'd love to hear from you/);
    const organizerHint = screen.getByRole('link', { name: /list it/i });
    expect(intro.compareDocumentPosition(faq) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(faq.compareDocumentPosition(organizerHint) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('keeps the locale prefix on the FAQ link', () => {
    renderWithProviders(<Contact />, { route: '/ru/contact' });
    expect(screen.getByRole('link', { name: 'Quick question? Check the FAQ first →' })).toHaveAttribute('href', '/ru/faq');
  });

  it('renders name, email, and message fields with submit button', () => {
    renderWithProviders(<Contact />);
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /email/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('submits form and shows success view', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Contact />);
    await userEvent.type(screen.getByLabelText(/name/i), 'Jane');
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'jane@example.com');
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
  });

  it('calls api.post with name, email, message, and empty honeypot', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Contact />);
    await userEvent.type(screen.getByLabelText(/name/i), 'Jane');
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'jane@example.com');
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/contact', {
        name: 'Jane',
        email: 'jane@example.com',
        message: 'Hello there',
        website: '',
      }),
    );
  });

  it('shows error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Bad request'));
    renderWithProviders(<Contact />);
    await userEvent.type(screen.getByLabelText(/name/i), 'Jane');
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'jane@example.com');
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Bad request')).toBeInTheDocument();
  });

  it('"send another" button resets to idle form', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Contact />);
    await userEvent.type(screen.getByLabelText(/name/i), 'Jane');
    await userEvent.type(screen.getByRole('textbox', { name: /email/i }), 'jane@example.com');
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => screen.getByRole('status'));
    await userEvent.click(screen.getByRole('button', { name: /another/i }));
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
  });

  it('does not fetch /users/me when signed out', () => {
    renderWithProviders(<Contact />);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('renders an organizer entry link pointing to /organizer/login', () => {
    renderWithProviders(<Contact />);
    const link = screen.getByRole('link', { name: /organizing an event/i });
    expect(link).toHaveAttribute('href', '/organizer/login');
  });
});
