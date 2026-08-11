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

  it('renders a marker on an option flagged with marker, and folds the state into its accessible name', () => {
    const markerOptions = [
      { value: 'et', label: 'ET' },
      { value: 'en', label: 'EN', marker: { state: 'partial' as const, stateLabel: 'partially translated' } },
    ];
    render(<SegmentedControl options={markerOptions} value="et" onChange={vi.fn()} ariaLabel="Language" />);
    expect(screen.getByRole('button', { name: 'EN, partially translated' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ET' }).querySelector('[aria-hidden="true"]')).not.toBeInTheDocument();
  });

  describe('dial variant', () => {
    it('renders the sliding indicator with --seg-count/--seg-index set for the active option', () => {
      const { container } = render(
        <SegmentedControl variant="dial" options={options} value="foryou" onChange={vi.fn()} ariaLabel="Mode" />
      );
      const track = container.querySelector('[role="group"]') as HTMLElement;
      expect(track.style.getPropertyValue('--seg-count')).toBe('2');
      expect(track.style.getPropertyValue('--seg-index')).toBe('1');
      expect(track.querySelector('[aria-hidden]')).toBeInTheDocument();
    });

    it('moves --seg-index when value changes', () => {
      const { container, rerender } = render(
        <SegmentedControl variant="dial" options={options} value="all" onChange={vi.fn()} ariaLabel="Mode" />
      );
      const track = container.querySelector('[role="group"]') as HTMLElement;
      expect(track.style.getPropertyValue('--seg-index')).toBe('0');

      rerender(<SegmentedControl variant="dial" options={options} value="foryou" onChange={vi.fn()} ariaLabel="Mode" />);
      expect(track.style.getPropertyValue('--seg-index')).toBe('1');
    });
  });
});
