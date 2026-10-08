import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { getResolvedTheme } from '../../lib/theme';
import PrefsMenu from './PrefsMenu';

describe('PrefsMenu', () => {
  it('trigger shows the locale code and declares a dialog popup', () => {
    renderWithProviders(<PrefsMenu locale="et" onLocaleChange={vi.fn()} />);

    const trigger = screen.getByRole('button', { name: 'Keel ja teema' });
    expect(trigger).toHaveTextContent('ET');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens a labelled dialog, focuses the current locale button, and groups Language / Theme', async () => {
    renderWithProviders(<PrefsMenu locale="en" onLocaleChange={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));

    const dialog = screen.getByRole('dialog', { name: 'Language and theme' });
    expect(within(dialog).getByRole('button', { name: 'EN' })).toHaveFocus();
    expect(within(dialog).getByRole('group', { name: 'Language' })).toBeInTheDocument();
    expect(within(dialog).getByRole('group', { name: 'Theme' })).toBeInTheDocument();
  });

  it('applies a theme override and reflects it with aria-pressed', async () => {
    renderWithProviders(<PrefsMenu locale="en" onLocaleChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));

    await userEvent.click(screen.getByRole('button', { name: 'Dark' }));

    expect(getResolvedTheme()).toBe('dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('disables the language buttons while a locale switch is pending', async () => {
    renderWithProviders(<PrefsMenu locale="en" onLocaleChange={vi.fn()} localeDisabled />);
    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));

    expect(screen.getByRole('button', { name: 'ET' })).toBeDisabled();
  });
});
