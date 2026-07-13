import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SegmentedControl from './SegmentedControl';

const options = [
  { value: 'all', label: 'All events' },
  { value: 'foryou', label: 'For you' },
];

describe('SegmentedControl', () => {
  it('renders every option', () => {
    render(<SegmentedControl options={options} value="all" onChange={vi.fn()} ariaLabel="Mode" />);
    expect(screen.getByRole('button', { name: 'All events' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'For you' })).toBeInTheDocument();
  });

  it('marks the active segment as pressed', () => {
    render(<SegmentedControl options={options} value="foryou" onChange={vi.fn()} ariaLabel="Mode" />);
    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All events' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('fires onChange with the clicked value', async () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={options} value="all" onChange={onChange} ariaLabel="Mode" />);
    await userEvent.click(screen.getByRole('button', { name: 'For you' }));
    expect(onChange).toHaveBeenCalledWith('foryou');
  });
});
