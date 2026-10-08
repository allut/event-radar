import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import DialMark from './DialMark';

describe('DialMark', () => {
  it('is decorative: aria-hidden, no accessible name', () => {
    const { container } = render(<DialMark />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('carries no intro class by default, so a static mark (Footer, AuthCard, reduced motion) never animates', () => {
    const { container } = render(<DialMark />);
    expect(container.querySelector('svg')!.getAttribute('class')).not.toMatch(/intro/);
  });

  it('adds the intro class only when animated', () => {
    const { container } = render(<DialMark animated />);
    expect(container.querySelector('svg')!.getAttribute('class')).toMatch(/intro/);
  });

  it('colours the hand and tip with --accent-ink and the rim/pivot with currentColor', () => {
    const { container } = render(<DialMark />);
    const accent = container.querySelectorAll('[stroke="var(--accent-ink)"], [fill="var(--accent-ink)"]');
    expect(accent).toHaveLength(2);
    expect(container.querySelector('circle[r="10.25"]')).toHaveAttribute('stroke', 'currentColor');
  });
});
