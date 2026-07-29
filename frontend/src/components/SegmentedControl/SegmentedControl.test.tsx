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

  it('renders a dot on an option flagged with dot: true', () => {
    const dotOptions = [
      { value: 'et', label: 'ET' },
      { value: 'en', label: 'EN', dot: true },
    ];
    render(<SegmentedControl options={dotOptions} value="et" onChange={vi.fn()} ariaLabel="Language" />);
    const enButton = screen.getByRole('button', { name: /EN/ });
    expect(enButton.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
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

    it('gives the dot the blip class under variant="dial" and not under the default variant', () => {
      const dotOptions = [
        { value: 'et', label: 'ET' },
        { value: 'en', label: 'EN', dot: true },
      ];
      const { rerender } = render(
        <SegmentedControl variant="dial" options={dotOptions} value="et" onChange={vi.fn()} ariaLabel="Language" />
      );
      const dialDot = screen.getByRole('button', { name: /EN/ }).querySelector('[aria-hidden="true"]');
      expect(dialDot?.className).toMatch(/blip/);

      rerender(<SegmentedControl options={dotOptions} value="et" onChange={vi.fn()} ariaLabel="Language" />);
      const plainDot = screen.getByRole('button', { name: /EN/ }).querySelector('[aria-hidden="true"]');
      expect(plainDot?.className).not.toMatch(/blip/);
    });
  });
});
