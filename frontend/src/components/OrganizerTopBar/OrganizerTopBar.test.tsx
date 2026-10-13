import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import OrganizerTopBar from './OrganizerTopBar';

vi.mock('../../api/client', () => ({
  api: { get: vi.fn() },
  organizerApi: { get: vi.fn() },
}));

import { api, organizerApi } from '../../api/client';

const mockOrganizerGet = vi.mocked(organizerApi.get);

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  mockOrganizerGet.mockReset();
  mockOrganizerGet.mockResolvedValue({ email: 'org@example.com', name: 'Jazz Club' });
});

describe('OrganizerTopBar', () => {
  it('links the brand mark home and shows "Your events" and "Your claims" in the nav', () => {
    renderWithProviders(<OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);

    expect(screen.getByRole('link', { name: 'Event Radar' })).toHaveAttribute('href', '/');
    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Your events', 'Your claims']);
    expect(links[0]).toHaveAttribute('href', '/organizer/dashboard');
    expect(links[1]).toHaveAttribute('href', '/organizer/claims');
  });

  it('has the gold New event CTA, no search and no pulse chip, and never fetches counts', async () => {
    renderWithProviders(<OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);

    expect(screen.getAllByRole('link', { name: 'New event' })[0]).toHaveAttribute('href', '/organizer/submit');
    expect(screen.queryByRole('search')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /on today/i })).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.get).not.toHaveBeenCalled();
    expect(mockOrganizerGet).not.toHaveBeenCalled();
  });

  it('puts Settings and Contact in the account menu and fetches the profile on open only', async () => {
    const onLogout = vi.fn();
    renderWithProviders(<OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={onLogout} />);

    await userEvent.click(screen.getByRole('button', { name: 'Account' }));

    expect(screen.getByRole('menuitem', { name: 'Settings' })).toHaveAttribute('href', '/organizer/settings');
    expect(screen.getByRole('menuitem', { name: 'Contact' })).toHaveAttribute('href', '/organizer/contact');
    // Name on one line, email on the next.
    expect(await screen.findByText('Jazz Club')).toBeInTheDocument();
    expect(screen.getByText('org@example.com')).toBeInTheDocument();
    expect(mockOrganizerGet).toHaveBeenCalledWith('/organizer/profile');

    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('drops the wordmark on phones: the logo link carries its own accessible name', () => {
    renderWithProviders(<OrganizerTopBar locale="ru" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);

    expect(screen.getByRole('link', { name: 'Event Radar' })).toHaveAttribute('aria-label', 'Event Radar');
  });

  it('the drawer carries the nav, account links and a Sign out button', async () => {
    renderWithProviders(<OrganizerTopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }));

    const hrefsFor = (name: string) => screen.getAllByRole('link', { name }).map((el) => el.getAttribute('href'));
    expect(hrefsFor('Your events')).toContain('/organizer/dashboard');
    expect(hrefsFor('Your claims')).toContain('/organizer/claims');
    expect(hrefsFor('Settings')).toContain('/organizer/settings');
    expect(hrefsFor('Contact')).toContain('/organizer/contact');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    await waitFor(() => expect(mockOrganizerGet).toHaveBeenCalled());
  });
});
