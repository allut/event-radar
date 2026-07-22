import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import TopBar from './TopBar';

describe('TopBar', () => {
  it('shows a Sign in link to /login when signed out, no sign-out button/nav/hamburger', () => {
    renderWithProviders(
      <TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />,
    );

    const signIn = screen.getByRole('link', { name: /sign in/i });
    expect(signIn).toHaveAttribute('href', '/login');
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Menu' })).not.toBeInTheDocument();
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
});
