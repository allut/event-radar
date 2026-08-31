import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Chip from './Chip';
import styles from './Chip.module.css';

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

  it('applies the active chip class to selected options', () => {
    render(<Chip options={options} selected={['music']} onToggle={vi.fn()} ariaLabel="Categories" />);
    expect(screen.getByRole('button', { name: 'Music' }).className).toContain(styles.activeChip);
    expect(screen.getByRole('button', { name: 'Theatre' }).className).not.toContain(styles.activeChip);
  });

  it('calls onToggle with the clicked value', async () => {
    const onToggle = vi.fn();
    render(<Chip options={options} selected={[]} onToggle={onToggle} ariaLabel="Categories" />);
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));
    expect(onToggle).toHaveBeenCalledWith('theater');
  });
});
