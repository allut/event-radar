import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LocaleSelector from './LocaleSelector';
import { LOCALES } from '../../constants';

describe('LocaleSelector', () => {
  it('renders all locales', () => {
    render(<LocaleSelector locale="en" onChange={vi.fn()} ariaLabel="Language" />);
    for (const { label } of LOCALES) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('active locale has aria-pressed=true', () => {
    render(<LocaleSelector locale="et" onChange={vi.fn()} ariaLabel="Language" />);
    const etBtn = screen.getByText('ET').closest('button')!;
    expect(etBtn).toHaveAttribute('aria-pressed', 'true');
    const enBtn = screen.getByText('EN').closest('button')!;
    expect(enBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onChange with locale code on click', async () => {
    const onChange = vi.fn();
    render(<LocaleSelector locale="en" onChange={onChange} ariaLabel="Language" />);
    await userEvent.click(screen.getByText('RU'));
    expect(onChange).toHaveBeenCalledWith('ru');
  });

  it('disables all buttons when disabled prop set', () => {
    render(<LocaleSelector locale="en" onChange={vi.fn()} ariaLabel="Language" disabled />);
    const buttons = screen.getAllByRole('button');
    for (const btn of buttons) {
      expect(btn).toBeDisabled();
    }
  });
});
