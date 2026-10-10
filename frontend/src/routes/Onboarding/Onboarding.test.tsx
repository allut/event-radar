import { describe, it, expect, vi } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Onboarding from './Onboarding';
import { renderWithProviders, LocationProbe } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
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

  it('submit is disabled when nothing selected', () => {
    renderWithProviders(<Onboarding />);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).toBeDisabled();
  });

  it('submit enables after selecting one persona', async () => {
    renderWithProviders(<Onboarding />);
    const personaBtn = screen.getAllByTitle('Select')[0];
    await userEvent.click(personaBtn);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).not.toBeDisabled();
  });

  it('on submit: calls api.post /onboarding/persona with ranked slugs', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    await userEvent.click(submitBtn);
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/onboarding/persona', {
        persona_slugs: expect.any(Array),
      }),
    );
  });

  it('shows error on submit failure', async () => {
    const { ApiError: ApiErrorClass } = await import('../../api/client');
    mockPost.mockRejectedValueOnce(new ApiErrorClass(StatusCodes.BAD_REQUEST, 'Bad request'));
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    await userEvent.click(submitBtn);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });

  it('clicking a selected persona again deselects it', async () => {
    renderWithProviders(<Onboarding />);
    const select = screen.getAllByTitle('Select')[0];
    await userEvent.click(select);

    const submitBtn = screen.getAllByRole('button').slice(-1)[0];
    expect(submitBtn).not.toBeDisabled();

    // same card now offers Deselect — clicking clears it
    await userEvent.click(screen.getByTitle('Deselect'));
    expect(submitBtn).toBeDisabled();
  });

  it('picking up to 3 ranks them, and a 4th click is a no-op until one is freed', async () => {
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    await userEvent.click(screen.getAllByTitle('Select')[0]);

    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();

    // at cap: remaining unselected cards are disabled
    const remaining = screen.queryAllByTitle('Select');
    for (const btn of remaining) {
      expect(btn).toBeDisabled();
    }
  });

  it('deselecting the first pick renumbers the rest', async () => {
    renderWithProviders(<Onboarding />);
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    await userEvent.click(screen.getAllByTitle('Select')[0]);

    const deselectButtons = screen.getAllByTitle('Deselect');
    await userEvent.click(deselectButtons[0]);

    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.queryByText('2')).not.toBeInTheDocument();
  });

  it('locale change calls setLocale and updates the URL', async () => {
    const { setLocale } = await import('../../lib/auth');
    const ui = (
      <>
        <Onboarding />
        <LocationProbe />
      </>
    );
    renderWithProviders(ui, {
      route: '/onboarding',
      routes: [
        { path: '/onboarding', element: ui },
        { path: '/:locale/onboarding', element: ui },
      ],
    });
    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));
    await userEvent.click(screen.getByRole('button', { name: 'RU' }));
    expect(setLocale).toHaveBeenCalledWith('ru');
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/ru/onboarding');
  });
});
