import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ThemeSelector from './ThemeSelector';
import { getThemePreference } from '../../lib/theme';

vi.mock('../../lib/auth', () => ({
  isAuthenticated: vi.fn(() => false),
}));
vi.mock('../../lib/organizerAuth', () => ({
  isAuthenticatedOrganizer: vi.fn(() => false),
}));
vi.mock('../../api/client', () => ({
  api: { patch: vi.fn(() => Promise.resolve()) },
  organizerApi: { patch: vi.fn(() => Promise.resolve()) },
}));

import { isAuthenticated } from '../../lib/auth';
import { isAuthenticatedOrganizer } from '../../lib/organizerAuth';
import { api, organizerApi } from '../../api/client';
const mockIsAuthenticated = vi.mocked(isAuthenticated);
const mockIsAuthenticatedOrganizer = vi.mocked(isAuthenticatedOrganizer);
const mockPatch = vi.mocked(api.patch);
const mockOrganizerPatch = vi.mocked(organizerApi.patch);

describe('ThemeSelector', () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mockIsAuthenticated.mockReturnValue(false);
    mockIsAuthenticatedOrganizer.mockReturnValue(false);
  });

  it('shows System on the trigger by default', () => {
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    expect(screen.getByRole('button', { name: 'System' })).toBeInTheDocument();
  });

  it('opens a popover listing all three options on trigger click', async () => {
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    for (const label of ['System', 'Light', 'Dark']) {
      expect(within(group).getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('active option has aria-pressed=true and reflects the current preference', async () => {
    localStorage.setItem('theme_preference', 'dark');
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    expect(within(group).getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('writes the selected option to localStorage.theme_preference and applies it', async () => {
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Light' }));

    expect(getThemePreference()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('button', { name: 'Light' })).toBeInTheDocument();
  });

  it('when signed out, selecting an option never PATCHes the account', async () => {
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));

    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('when signed in, selecting Light/Dark PATCHes theme_preference to the account', async () => {
    mockIsAuthenticated.mockReturnValue(true);
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));

    expect(mockPatch).toHaveBeenCalledWith('/users/me', { theme_preference: 'dark' });
  });

  it('when signed in, selecting System PATCHes theme_preference: null to clear the account (#257)', async () => {
    mockIsAuthenticated.mockReturnValue(true);
    localStorage.setItem('theme_preference', 'dark');
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'System' }));

    expect(mockPatch).toHaveBeenCalledWith('/users/me', { theme_preference: null });
  });

  it('when signed in as an organizer, selecting Light/Dark PATCHes theme_preference to the organizer account', async () => {
    mockIsAuthenticatedOrganizer.mockReturnValue(true);
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));

    expect(mockOrganizerPatch).toHaveBeenCalledWith('/organizer/profile', { theme_preference: 'dark' });
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('when signed in as an organizer, selecting System PATCHes theme_preference: null to clear the organizer account', async () => {
    mockIsAuthenticatedOrganizer.mockReturnValue(true);
    localStorage.setItem('theme_preference', 'dark');
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'System' }));

    expect(mockOrganizerPatch).toHaveBeenCalledWith('/organizer/profile', { theme_preference: null });
  });

  it('when signed in as both consumer and organizer, the consumer PATCH takes precedence', async () => {
    mockIsAuthenticated.mockReturnValue(true);
    mockIsAuthenticatedOrganizer.mockReturnValue(true);
    render(<ThemeSelector locale="en" ariaLabel="Theme" />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));

    expect(mockPatch).toHaveBeenCalledWith('/users/me', { theme_preference: 'dark' });
    expect(mockOrganizerPatch).not.toHaveBeenCalled();
  });
});
