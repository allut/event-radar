import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminThemeToggle from './AdminThemeToggle';
import { getResolvedTheme } from '../../lib/theme';

describe('AdminThemeToggle', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('shows the device-resolved theme (Light) on the trigger by default', () => {
    render(<AdminThemeToggle />);
    expect(screen.getByRole('button', { name: 'Light' })).toBeInTheDocument();
  });

  it('opens a popover listing exactly two options on trigger click — no System entry', async () => {
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Light' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    for (const label of ['Light', 'Dark']) {
      expect(within(group).getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: 'System' })).not.toBeInTheDocument();
  });

  it('active option has aria-pressed=true and reflects the resolved theme', async () => {
    localStorage.setItem('theme_override', 'dark');
    localStorage.setItem('theme_override_device', 'light');
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    expect(within(group).getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('writes the selected option as a browser-local override and applies it immediately', async () => {
    render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Light' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));

    expect(getResolvedTheme()).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toBeInTheDocument();
  });

  it('persists across a remount, mirroring a reload/new session', async () => {
    const { unmount } = render(<AdminThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Light' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await userEvent.click(within(group).getByRole('button', { name: 'Dark' }));
    unmount();

    render(<AdminThemeToggle />);
    expect(screen.getByRole('button', { name: 'Dark' })).toBeInTheDocument();
  });
});
