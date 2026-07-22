import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Onboarding from './Onboarding';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  // Real ApiError (shared class, no network dependency); only api.* stubbed.
  ...(await importOriginal<typeof import('../../api/client')>()),
  api: {
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);

describe('Onboarding', () => {
  it('renders persona cards', () => {
    renderWithProviders(<Onboarding />);
    expect(screen.getAllByRole('button').length).toBeGreaterThan(1);
  });

  it('submit is disabled when no primary selected', () => {
    renderWithProviders(<Onboarding />);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).toBeDisabled();
  });

  it('submit enables after selecting a primary persona', async () => {
    renderWithProviders(<Onboarding />);
    const personaBtn = screen.getAllByTitle('Set as primary')[0];
    await userEvent.click(personaBtn);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).not.toBeDisabled();
  });

  it('on submit: calls api.post /onboarding/persona', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Set as primary')[0]);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    await userEvent.click(submitBtn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/onboarding/persona', expect.any(Object)));
  });

  it('shows error on submit failure', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Bad request'));
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Set as primary')[0]);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    await userEvent.click(submitBtn);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });

  it('clicking the primary persona again deselects it', async () => {
    renderWithProviders(<Onboarding />);
    const setPrimary = screen.getAllByTitle('Set as primary')[0];
    await userEvent.click(setPrimary);

    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).not.toBeDisabled();

    // same card now offers Deselect — clicking clears the primary
    await userEvent.click(screen.getByTitle('Deselect'));
    expect(submitBtn).toBeDisabled();
  });

  it('secondary can be set and toggled off', async () => {
    renderWithProviders(<Onboarding />);
    // set a primary on the first card so other cards expose the secondary action
    await userEvent.click(screen.getAllByTitle('Set as primary')[0]);

    const setSecondary = screen.getAllByTitle('Set as secondary')[0];
    await userEvent.click(setSecondary);

    // now a Remove secondary control exists; toggling it off removes the choice
    const removeSecondary = screen.getByTitle('Remove secondary');
    await userEvent.click(removeSecondary);
    expect(screen.queryByTitle('Remove secondary')).not.toBeInTheDocument();
  });

  it('locale change calls setLocale', async () => {
    const { setLocale } = await import('../../lib/auth');
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getByRole('button', { name: 'EN' }));
    await userEvent.click(screen.getByRole('button', { name: 'RU' }));
    expect(setLocale).toHaveBeenCalledWith('ru');
  });
});
