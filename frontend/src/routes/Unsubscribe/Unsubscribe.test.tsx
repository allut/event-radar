import { t } from '../../i18n';
import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Unsubscribe from './Unsubscribe';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: {
    post: vi.fn(),
  },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('Unsubscribe', () => {
  it('shows error when no token in URL', () => {
    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows working state initially when token present', () => {
    mockPost.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe?token=abc' });
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('fires the unsubscribe POST on mount', () => {
    mockPost.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe?token=abc123' });
    expect(mockPost).toHaveBeenCalledWith('/email/unsubscribe?token=abc123');
  });

  it('on success: shows the success state with an Undo button', async () => {
    mockPost.mockResolvedValueOnce({ ok: true, email: 't***@example.com' });

    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe?token=valid' });

    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('Undo triggers resubscribe and shows resubscribed state', async () => {
    mockPost
      .mockResolvedValueOnce({ ok: true, email: 't***@example.com' })
      .mockResolvedValueOnce({ ok: true, email: 't***@example.com' });

    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe?token=valid' });
    await waitFor(() => expect(screen.getByRole('button')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button'));

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/email/resubscribe?token=valid')
    );
  });

  it('on verify failure: shows error state', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Link expired'));

    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe?token=expired' });

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});

describe('Unsubscribe locale', () => {
  // The page speaks the URL's language (like the Footer under it, #497) —
  // never the saved preference, mocked to 'en' above.
  it('renders in the URL prefix\'s language', () => {
    renderWithProviders(<Unsubscribe />, { route: '/ru/unsubscribe' });
    expect(screen.getAllByText(t('unsubscribe.error', 'ru')).length).toBeGreaterThan(0);
  });

  it('renders Estonian on a bare path', () => {
    renderWithProviders(<Unsubscribe />, { route: '/unsubscribe' });
    expect(screen.getAllByText(t('unsubscribe.error', 'et')).length).toBeGreaterThan(0);
  });
});
