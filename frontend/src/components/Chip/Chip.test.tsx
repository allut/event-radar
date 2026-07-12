import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Chip from './Chip';

const options = [
  { value: 'music', label: 'Music' },
  { value: 'theater', label: 'Theatre' },
];

describe('Chip', () => {
  it('marks selected options as pressed', () => {
    render(<Chip options={options} selected={['music']} onToggle={vi.fn()} ariaLabel="Categories" />);
    expect(screen.getByRole('button', { name: 'Music' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Theatre' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onToggle with the clicked value', async () => {
    const onToggle = vi.fn();
    render(<Chip options={options} selected={[]} onToggle={onToggle} ariaLabel="Categories" />);
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));
    expect(onToggle).toHaveBeenCalledWith('theater');
  });
});
