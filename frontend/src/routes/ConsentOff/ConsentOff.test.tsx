import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { t } from '../../i18n';
import ConsentOff from './ConsentOff';
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

import { api, ApiError } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('ConsentOff', () => {
  it('shows an error when the URL has no token', () => {
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off' });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('strips the token from the address bar and POSTs on load', () => {
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState');
    mockPost.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off?token=abc' });
    expect(replaceStateSpy).toHaveBeenCalledWith({}, '', '/email-consent-off');
    expect(mockPost).toHaveBeenCalledWith('/email/ads-off?token=abc');
    replaceStateSpy.mockRestore();
  });

  it('shows Done with an Undo button on success', async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off?token=ok' });
    expect(await screen.findByText(t('consent_off.done', 'et'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('consent_off.undo', 'et') })).toBeInTheDocument();
  });

  it('Undo POSTs ads-on and shows the undone copy', async () => {
    mockPost.mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ok: true });
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off?token=ok' });
    await userEvent.click(await screen.findByRole('button'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/email/ads-on?token=ok'));
    expect(await screen.findByText(t('consent_off.undone', 'et'))).toBeInTheDocument();
  });

  it('shows the expired copy on a 400', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(StatusCodes.BAD_REQUEST, 'bad'));
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off?token=old' });
    expect(await screen.findByText(t('consent_off.expired', 'et'))).toBeInTheDocument();
    expect(screen.getByRole('link')).toBeInTheDocument();
  });

  it('shows the generic error on other failures', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(StatusCodes.INTERNAL_SERVER_ERROR, 'boom'));
    renderWithProviders(<ConsentOff />, { route: '/email-consent-off?token=x' });
    expect(await screen.findByText(t('unsubscribe.error', 'et'))).toBeInTheDocument();
  });

  it('renders in the URL prefix language', () => {
    renderWithProviders(<ConsentOff />, { route: '/ru/email-consent-off' });
    expect(screen.getAllByText(t('unsubscribe.error', 'ru')).length).toBeGreaterThan(0);
  });
});
