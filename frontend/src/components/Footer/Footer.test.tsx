import { describe, it, expect, beforeEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { setLocale } from '../../lib/auth';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { LOCALE_KEY, ORGANIZER_SIGNED_IN_HINT_KEY } from '../../constants';
import Footer from './Footer';

describe('Footer', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders brand, legal links, social icons, and copyright', () => {
    renderWithProviders(<Footer />);

    // Brand line
    expect(screen.getByText(/Tallinn/)).toBeInTheDocument();

    // Brand links back to the consumer site
    expect(screen.getByRole('link', { name: "What's on Radar" })).toHaveAttribute('href', '/');

    // Legal links point at the stub routes
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/contact');

    // Signed-out organizer link points at the organizer login
    expect(screen.getByRole('link', { name: 'For organizers' })).toHaveAttribute('href', '/organizer/login');

    // Social links: labelled, open in a new tab, hardened rel
    const instagram = screen.getByRole('link', { name: 'Instagram' });
    expect(instagram).toHaveAttribute('href', 'https://instagram.com/');
    expect(instagram).toHaveAttribute('target', '_blank');
    expect(instagram).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByRole('link', { name: 'Facebook' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'X' })).toBeInTheDocument();

    // Copyright carries the current year
    expect(
      screen.getByText(new RegExp(`© ${new Date().getFullYear()}`)),
    ).toBeInTheDocument();
  });

  it('reflects the active locale reactively via the locale store', () => {
    localStorage.setItem(LOCALE_KEY, 'et');
    renderWithProviders(<Footer />);
    // Estonian labels
    expect(screen.getByRole('link', { name: 'Privaatsus' })).toBeInTheDocument();

    // Switching locale through the store re-renders the footer
    act(() => setLocale('ru'));
    expect(screen.getByRole('link', { name: 'Конфиденциальность' })).toBeInTheDocument();
  });

  it('swaps the organizer link to the dashboard once an organizer session exists', () => {
    renderWithProviders(<Footer />);
    expect(screen.getByRole('link', { name: 'For organizers' })).toHaveAttribute('href', '/organizer/login');

    act(() => setOrganizerSignedInHint());
    expect(screen.getByRole('link', { name: 'Organizer dashboard' })).toHaveAttribute('href', '/organizer/dashboard');
  });

  it('reads an already-active organizer session on first render', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />);
    expect(screen.getByRole('link', { name: 'Organizer dashboard' })).toHaveAttribute('href', '/organizer/dashboard');
  });

  it('carries the current locale prefix into every link, with no pathPattern (mirrors Footer being mounted outside <Routes> in App.tsx)', () => {
    renderWithProviders(<Footer />, { route: '/ru/contact' });

    expect(screen.getByRole('link', { name: "What's on Radar" })).toHaveAttribute('href', '/ru');
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/ru/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/ru/terms');
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/ru/contact');
    expect(screen.getByRole('link', { name: 'For organizers' })).toHaveAttribute('href', '/ru/organizer/login');
  });
});
