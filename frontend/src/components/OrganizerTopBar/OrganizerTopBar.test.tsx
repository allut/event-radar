import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
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
});
