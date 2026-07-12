import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Toggle from './Toggle';

describe('Toggle', () => {
  it('reflects the on state via aria-pressed', () => {
    render(<Toggle on={true} onChange={vi.fn()} ariaLabel="Digest" />);
    expect(screen.getByRole('button', { name: 'Digest' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls onChange with the flipped value', async () => {
    const onChange = vi.fn();
    render(<Toggle on={false} onChange={onChange} ariaLabel="Digest" />);
    await userEvent.click(screen.getByRole('button', { name: 'Digest' }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('does not call onChange when disabled', async () => {
    const onChange = vi.fn();
    render(<Toggle on={false} onChange={onChange} ariaLabel="Digest" disabled />);
    await userEvent.click(screen.getByRole('button', { name: 'Digest' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
