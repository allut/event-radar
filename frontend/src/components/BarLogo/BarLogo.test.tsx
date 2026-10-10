import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import BarLogo from './BarLogo';

// The intro flag is module-level (one play per page load), and vitest isolates
// modules per file — so the first mount in this file is the page's first mount.
describe('BarLogo', () => {
  it('plays the Dial intro on the first mount of the page load only', () => {
    const first = renderWithProviders(<BarLogo locale="en" />);
    expect(first.container.querySelector('svg')!.getAttribute('class')).toMatch(/intro/);
    first.unmount();

    // Every route mounts its own bar: a later mount must not replay it.
    const second = renderWithProviders(<BarLogo locale="en" />);
    expect(second.container.querySelector('svg')!.getAttribute('class')).not.toMatch(/intro/);
  });

  it('links home under the locale prefix, named by the brand, with "Radar" as the gold italic', () => {
    renderWithProviders(<BarLogo locale="ru" />, { route: '/ru/explore' });

    const link = screen.getByRole('link', { name: 'Event Radar' });
    expect(link).toHaveAttribute('href', '/ru');
    expect(link.querySelector('em')).toHaveTextContent('Radar');
  });

  it('gives the mark-only (organizer phone) variant an explicit aria-label', () => {
    renderWithProviders(<BarLogo locale="en" markOnlyOnPhone />);
    expect(screen.getByRole('link', { name: 'Event Radar' })).toHaveAttribute('aria-label', 'Event Radar');
  });
});
