import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LocaleSelector from './LocaleSelector';
import { LOCALES } from '../../constants';

describe('LocaleSelector', () => {
  it('shows the current locale on the trigger', () => {
    render(<LocaleSelector locale="en" onChange={vi.fn()} ariaLabel="Language" />);
    expect(screen.getByRole('button', { name: 'EN' })).toBeInTheDocument();
  });

  it('opens a popover listing all locales on trigger click', async () => {
    render(<LocaleSelector locale="en" onChange={vi.fn()} ariaLabel="Language" />);
    await userEvent.click(screen.getByRole('button', { name: 'EN' }));
    const group = screen.getByRole('group', { name: 'Language' });
    for (const { label } of LOCALES) {
      expect(within(group).getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('active locale option has aria-pressed=true', async () => {
    render(<LocaleSelector locale="et" onChange={vi.fn()} ariaLabel="Language" />);
    await userEvent.click(screen.getByRole('button', { name: 'ET' }));
    const group = screen.getByRole('group', { name: 'Language' });
    expect(within(group).getByRole('button', { name: 'ET' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'EN' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onChange with locale code on option click', async () => {
    const onChange = vi.fn();
    render(<LocaleSelector locale="en" onChange={onChange} ariaLabel="Language" />);
    await userEvent.click(screen.getByRole('button', { name: 'EN' }));
    const group = screen.getByRole('group', { name: 'Language' });
    await userEvent.click(within(group).getByRole('button', { name: 'RU' }));
    expect(onChange).toHaveBeenCalledWith('ru');
  });

  it('disables the trigger when disabled prop set', () => {
    render(<LocaleSelector locale="en" onChange={vi.fn()} ariaLabel="Language" disabled />);
    expect(screen.getByRole('button', { name: 'EN' })).toBeDisabled();
  });
});
