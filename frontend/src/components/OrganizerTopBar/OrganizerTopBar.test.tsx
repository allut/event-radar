import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import OrganizerTopBar from './OrganizerTopBar';

describe('OrganizerTopBar', () => {
  it('links the brand mark to the public site and keeps the dashboard nav link intact', () => {
    renderWithProviders(
      <OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    expect(screen.getByRole('link', { name: "What's on Radar" })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'Your events' })).toHaveAttribute(
      'href',
      '/organizer/dashboard',
    );
  });

  it('renders a mobile menu trigger whose popover carries the three organizer nav links', () => {
    renderWithProviders(
      <OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    // Desktop nav already renders these same labels, so the popover ones are
    // duplicates by accessible name — assert on the set of hrefs instead of
    // a single unique match.
    const hrefsFor = (name: string) =>
      screen.getAllByRole('link', { name }).map((el) => el.getAttribute('href'));

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(hrefsFor('Your events')).toContain('/organizer/dashboard');
    expect(hrefsFor('New event')).toContain('/organizer/submit');
    expect(hrefsFor('Settings')).toContain('/organizer/settings');
  });
});
