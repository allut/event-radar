import { describe, it, expect, beforeEach } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { useNavigate } from 'react-router-dom';
import { renderWithProviders } from '../../test/utils';
import { setLocale } from '../../lib/auth';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { ORGANIZER_SIGNED_IN_HINT_KEY } from '../../constants/auth';
import { LOCALE_KEY } from '../../constants/core';
import Footer from './Footer';

describe('Footer', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders brand, legal links, social icons, and copyright', () => {
    renderWithProviders(<Footer />, { route: '/en' });

    // Brand line
    expect(screen.getByText(/Tallinn/)).toBeInTheDocument();

    // Brand links back to the consumer site
    expect(screen.getByRole('link', { name: 'Event Radar' })).toHaveAttribute('href', '/en');

    // Legal links point at the stub routes
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/en/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/en/terms');
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/en/contact');

    // Signed-out organizer link points at the organizer login
    expect(screen.getByRole('link', { name: 'For organizers' })).toHaveAttribute('href', '/en/organizer/login');

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

  it('places the FAQ link between Terms and Contact', () => {
    renderWithProviders(<Footer />, { route: '/en' });

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Privacy', 'Terms', 'FAQ', 'Contact', 'For organizers']);
    expect(screen.getByRole('link', { name: 'FAQ' })).toHaveAttribute('href', '/en/faq');
  });

  it('keeps the FAQ link on the public /faq from an organizer-portal page', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />, { route: '/en/organizer/dashboard' });

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Privacy', 'Terms', 'FAQ', 'Contact', 'Organizer dashboard']);
    expect(screen.getByRole('link', { name: 'FAQ' })).toHaveAttribute('href', '/en/faq');
  });

  it('speaks the URL prefix\'s language with no saved preference', () => {
    renderWithProviders(<Footer />, { route: '/ru/organizer/contact' });

    const links = within(screen.getByRole('navigation', { name: 'Подвал' })).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(
      ['Конфиденциальность', 'Условия', 'Вопросы и ответы', 'Контакты', 'Организаторам'],
    );
  });

  it('speaks Estonian on a bare path with no saved preference', () => {
    renderWithProviders(<Footer />, { route: '/contact' });

    const links = within(screen.getByRole('navigation', { name: 'Jalus' })).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Privaatsus', 'Tingimused', 'KKK', 'Kontakt', 'Korraldajatele']);
  });

  it('follows the URL over a saved preference that disagrees with it', () => {
    localStorage.setItem(LOCALE_KEY, 'en');
    const { unmount } = renderWithProviders(<Footer />, { route: '/faq' });
    expect(screen.getByRole('link', { name: 'Privaatsus' })).toHaveAttribute('href', '/privacy');
    unmount();

    renderWithProviders(<Footer />, { route: '/ru/faq' });
    expect(screen.getByRole('link', { name: 'Конфиденциальность' })).toHaveAttribute('href', '/ru/privacy');
  });

  it('re-renders in the new language when a locale switch navigates to the new prefix', () => {
    function SwitchToRu() {
      const navigate = useNavigate();
      return <button onClick={() => { setLocale('ru'); navigate('/ru/explore', { replace: true }); }}>ru</button>;
    }
    renderWithProviders(<><SwitchToRu /><Footer /></>, { route: '/explore' });
    expect(screen.getByRole('link', { name: 'Privaatsus' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ru' }));
    expect(screen.getByRole('link', { name: 'Конфиденциальность' })).toHaveAttribute('href', '/ru/privacy');
  });

  it('swaps the organizer link to the dashboard once an organizer session exists', () => {
    renderWithProviders(<Footer />, { route: '/en' });
    expect(screen.getByRole('link', { name: 'For organizers' })).toHaveAttribute('href', '/en/organizer/login');

    act(() => setOrganizerSignedInHint());
    expect(screen.getByRole('link', { name: 'Organizer dashboard' })).toHaveAttribute('href', '/en/organizer/dashboard');
  });

  it('reads an already-active organizer session on first render', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />, { route: '/en' });
    expect(screen.getByRole('link', { name: 'Organizer dashboard' })).toHaveAttribute('href', '/en/organizer/dashboard');
  });

  it('carries the current locale prefix into every link, with no pathPattern (mirrors Footer being mounted outside <Routes> in App.tsx)', () => {
    renderWithProviders(<Footer />, { route: '/ru/contact' });

    expect(screen.getByRole('link', { name: 'Event Radar' })).toHaveAttribute('href', '/ru');
    expect(screen.getByRole('link', { name: 'Конфиденциальность' })).toHaveAttribute('href', '/ru/privacy');
    expect(screen.getByRole('link', { name: 'Условия' })).toHaveAttribute('href', '/ru/terms');
    expect(screen.getByRole('link', { name: 'Вопросы и ответы' })).toHaveAttribute('href', '/ru/faq');
    expect(screen.getByRole('link', { name: 'Контакты' })).toHaveAttribute('href', '/ru/contact');
    expect(screen.getByRole('link', { name: 'Организаторам' })).toHaveAttribute('href', '/ru/organizer/login');
  });

  it('links Contact to the public form on a consumer-portal page even when signed in as an organizer', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />, { route: '/explore' });
    expect(screen.getByRole('link', { name: 'Kontakt' })).toHaveAttribute('href', '/contact');
  });

  it('links Contact to the public form on an organizer-portal page while signed out', () => {
    renderWithProviders(<Footer />, { route: '/organizer/login' });
    expect(screen.getByRole('link', { name: 'Kontakt' })).toHaveAttribute('href', '/contact');
  });

  it('links Contact to the authenticated organizer form on an organizer-portal page while signed in', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />, { route: '/organizer/dashboard' });
    expect(screen.getByRole('link', { name: 'Kontakt' })).toHaveAttribute('href', '/organizer/contact');
  });

  it('keeps the locale prefix on the organizer contact link', () => {
    localStorage.setItem(ORGANIZER_SIGNED_IN_HINT_KEY, '1');
    renderWithProviders(<Footer />, { route: '/ru/organizer/settings' });
    expect(screen.getByRole('link', { name: 'Контакты' })).toHaveAttribute('href', '/ru/organizer/contact');
  });
});
