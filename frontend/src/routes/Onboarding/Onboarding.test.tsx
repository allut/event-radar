import { describe, it, expect, vi, beforeEach } from 'vitest';
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
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { api } from '../../api/client';
const mockPost = vi.mocked(api.post);
const mockGet = vi.mocked(api.get);

beforeEach(() => {
  mockGet.mockResolvedValue({ email_digest_opt_in: false });
});

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
        email_digest_opt_in: false,
      }),
    );
  });

  it('digest checkbox starts unticked for a user who has not opted in', async () => {
    renderWithProviders(<Onboarding />);
    const box = await screen.findByRole('checkbox', { name: /daily five each morning/i });
    expect(box).not.toBeChecked();
    expect(screen.getByText('Daily Five email is off.')).toBeInTheDocument();
  });

  it('ticking the digest checkbox sends email_digest_opt_in: true', async () => {
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Onboarding />);
    await userEvent.click(await screen.findByRole('checkbox', { name: /daily five each morning/i }));
    expect(screen.getByText(/Daily Five email is on/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    await userEvent.click(screen.getAllByRole('button').slice(-1)[0]);
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/onboarding/persona', {
        persona_slugs: expect.any(Array),
        email_digest_opt_in: true,
      }),
    );
  });

  it('shows the saved choice for a user who re-picks personas', async () => {
    mockGet.mockResolvedValue({ email_digest_opt_in: true });
    renderWithProviders(<Onboarding />);
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: /daily five each morning/i })).toBeChecked(),
    );
  });

  it('omits the digest field when the saved choice could not be read', async () => {
    mockGet.mockRejectedValue(new Error('boom'));
    mockPost.mockResolvedValueOnce(undefined);
    renderWithProviders(<Onboarding />);
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: /daily five each morning/i })).toBeEnabled(),
    );
    await userEvent.click(screen.getAllByTitle('Select')[0]);
    await userEvent.click(screen.getAllByRole('button').slice(-1)[0]);
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
