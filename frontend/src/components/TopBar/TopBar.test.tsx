import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import TopBar from './TopBar';

describe('TopBar', () => {
  it('shows a Sign in link to /login when signed out, no sign-out button, only Explore in nav, plus hamburger', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />,
    );

    const signIn = screen.getByRole('link', { name: /sign in/i });
    expect(signIn).toHaveAttribute('href', '/login');
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Explore' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Daily 5' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Saved' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
  });

  it('shows Back immediately alongside Sign in when signed out with onBack', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} authed={false} onBack={vi.fn()} />,
    );

    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows a Sign out button when signed in', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} authed />,
    );

    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /sign in/i })).not.toBeInTheDocument();
  });

  it('hides nav links but keeps Sign out and hamburger when showNav is false', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} authed showNav={false} />,
    );

    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
  });

  it('carries the current URL locale prefix into every nav link href, and keeps the active-nav highlight under a prefixed route', () => {
    // locale="en" drives the rendered text (independent of the route); the
    // href prefix comes from useLocalePath, which reads the URL — kept
    // deliberately mismatched here so the assertions can use English names
    // while still proving the href is prefixed from the route.
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} authed />,
      { route: '/ru/explore' },
    );

    const exploreLink = screen.getByRole('link', { name: 'Explore' });
    expect(exploreLink).toHaveAttribute('href', '/ru/explore');
    expect(exploreLink.className).toMatch(/navLinkActive/);
    expect(screen.getByRole('link', { name: 'Daily 5' })).toHaveAttribute('href', '/ru');
    expect(screen.getByRole('link', { name: 'Saved' })).toHaveAttribute('href', '/ru/saved');
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/ru/settings');
  });

  it('carries the locale prefix into the Sign in link href when signed out on a prefixed route', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />,
      { route: '/ru/events/1' },
    );

    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/ru/login');
  });
});
