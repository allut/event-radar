import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminThemeToggle from './AdminThemeToggle';
import { getThemePreference } from '../../lib/theme';

describe('AdminThemeToggle', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('shows System on the trigger by default', () => {
    render(<AdminThemeToggle />);
    expect(screen.getByRole('button', { name: 'System' })).toBeInTheDocument();
  });

  it('opens a popover listing all three options on trigger click', async () => {
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    for (const label of ['System', 'Light', 'Dark']) {
      expect(within(group).getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('active option has aria-pressed=true and reflects the current preference', async () => {
    localStorage.setItem('theme_preference', 'dark');
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    expect(within(group).getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('writes the selected option to localStorage.theme_preference and applies it immediately', async () => {
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Light' }));

    expect(getThemePreference()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('button', { name: 'Light' })).toBeInTheDocument();
  });

  it('persists across a remount, mirroring a reload/new session', async () => {
    const { unmount } = render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));
    unmount();

    render(<AdminThemeToggle />);
    expect(screen.getByRole('button', { name: 'Dark' })).toBeInTheDocument();
  });
});
