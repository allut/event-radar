import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatusCodes } from 'http-status-codes';
import OrganizerContact from './OrganizerContact';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

import { organizerApi } from '../../api/client';
const mockPost = vi.mocked(organizerApi.post);

beforeEach(() => {
  mockPost.mockReset();
});

describe('OrganizerContact', () => {
  it('renders a message field and submit button', () => {
    renderWithProviders(<OrganizerContact />);
    expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('submits the message and shows success view', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<OrganizerContact />);
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
    expect(mockPost).toHaveBeenCalledWith('/organizer/contact', { message: 'Hello there' });
  });

  it('shows error message on ApiError', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Bad request'));
    renderWithProviders(<OrganizerContact />);
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('Bad request')).toBeInTheDocument();
  });

  it('"send another" button resets to idle form', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<OrganizerContact />);
    await userEvent.type(screen.getByLabelText(/message/i), 'Hello there');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    await waitFor(() => screen.getByRole('status'));
    await userEvent.click(screen.getByRole('button', { name: /another/i }));
    expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
  });

  it('disables submit until a message is entered', () => {
    renderWithProviders(<OrganizerContact />);
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });
});
