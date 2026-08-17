import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatusCodes } from 'http-status-codes';
import MagicLinkForm from './MagicLinkForm';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: { post: vi.fn() },
  organizerApi: { post: vi.fn() },
}));

import { api, organizerApi } from '../../api/client';
const mockPost = vi.mocked(api.post);
const mockOrganizerPost = vi.mocked(organizerApi.post);

describe('MagicLinkForm', () => {
  it('renders an email input and submit button', () => {
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('disables submit until an email is entered', async () => {
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    const submit = screen.getByRole('button', { name: /send/i });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    expect(submit).toBeEnabled();
  });

  it('submits through the consumer api client by default', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/auth/request-link', {
        email: 'jane@example.com',
        locale: 'en',
      }),
    );
    expect(mockOrganizerPost).not.toHaveBeenCalled();
  });

  it('submits through the organizer api client when organizer=true', async () => {
    mockOrganizerPost.mockResolvedValueOnce(undefined);
    renderWithProviders(
      <MagicLinkForm
        locale="en"
        emailFieldId="email-1"
        organizer
        requestPath="/organizer/auth/request-link"
      />,
    );
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() =>
      expect(mockOrganizerPost).toHaveBeenCalledWith('/organizer/auth/request-link', {
        email: 'jane@example.com',
        locale: 'en',
      }),
    );
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows the success view with the submitted email after a successful submit', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
  });

  it('"use a different address" resets back to the form', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => screen.getByRole('status'));
    await userEvent.click(screen.getByRole('button', { name: /different/i }));
    expect(screen.getByLabelText(/email/i)).toHaveValue('');
  });

  it('shows an error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Bad request'));
    renderWithProviders(<MagicLinkForm locale="en" emailFieldId="email-1" />);
    await userEvent.type(screen.getByLabelText(/email/i), 'jane@example.com');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Bad request')).toBeInTheDocument();
  });
});
