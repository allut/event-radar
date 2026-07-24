import { describe, it, expect, beforeEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { setLocale } from '../../lib/auth';
import { LOCALE_KEY } from '../../constants';
import Footer from './Footer';

describe('Footer', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders brand, legal links, social icons, and copyright', () => {
    renderWithProviders(<Footer />);

    // Brand line
    expect(screen.getByText(/Tallinn/)).toBeInTheDocument();

    // Legal links point at the stub routes
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/contact');

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
});
