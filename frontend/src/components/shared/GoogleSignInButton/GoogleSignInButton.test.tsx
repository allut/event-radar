import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import GoogleSignInButton from './GoogleSignInButton';

describe('GoogleSignInButton', () => {
  it('renders a plain link to the given href, no client-side handler', () => {
    render(<GoogleSignInButton href="/api/organizer/auth/google/start" locale="en" />);
    const link = screen.getByRole('link', { name: 'Sign in with Google' });
    expect(link).toHaveAttribute('href', '/api/organizer/auth/google/start');
  });

  it('renders the localized label per locale', () => {
    render(<GoogleSignInButton href="/api/organizer/auth/google/start" locale="et" />);
    expect(screen.getByRole('link', { name: "Logi sisse Google'i kontoga" })).toBeInTheDocument();
  });

  it('renders the Google mark as an inline SVG, never an <img>', () => {
    const { container } = render(<GoogleSignInButton href="/api/organizer/auth/google/start" locale="en" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });

  it('renders the classic four-colour Google G brand fills', () => {
    const { container } = render(<GoogleSignInButton href="/api/organizer/auth/google/start" locale="en" />);
    const fills = [...container.querySelectorAll('path')].map((p) => p.getAttribute('fill'));
    expect(fills).toEqual(expect.arrayContaining(['#4285F4', '#34A853', '#FBBC05', '#EA4335']));
  });
});
