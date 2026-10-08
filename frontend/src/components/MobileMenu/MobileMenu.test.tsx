import { describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { getResolvedTheme } from '../../lib/theme';
import MobileMenu from './MobileMenu';

vi.mock('../../api/client', () => ({
  api: { get: vi.fn().mockResolvedValue({ email: 'ada@example.com' }) },
  organizerApi: { get: vi.fn() },
}));

describe('MobileMenu', () => {
  it('toggles the popover on trigger click', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByText('Daily 5')).toBeInTheDocument();
  });

  it('navigates and closes on a nav link click', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('Explore'));

    expect(screen.queryByText('Explore')).not.toBeInTheDocument();
  });

  it('fires onLocaleChange and closes on a locale click', () => {
    const onLocaleChange = vi.fn();
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={onLocaleChange} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('ET'));

    expect(onLocaleChange).toHaveBeenCalledWith('et');
    expect(screen.queryByText('ET')).not.toBeInTheDocument();
  });

  it('fires onLogout and closes on sign out click', () => {
    const onLogout = vi.fn();
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={onLogout} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('Sign out'));

    expect(onLogout).toHaveBeenCalled();
    expect(screen.queryByText('Sign out')).not.toBeInTheDocument();
  });

  it('closes on Escape', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByText('Daily 5')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();
  });

  it('hides nav links but keeps locale + sign out when showNav is false', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} showNav={false} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();
    expect(screen.queryByText('Explore')).not.toBeInTheDocument();
    expect(screen.getByText('Sign out')).toBeInTheDocument();
    expect(screen.getByText('ET')).toBeInTheDocument();
  });

  it('carries the current URL locale prefix into nav link hrefs and keeps the active-nav highlight under a prefixed route', () => {
    // locale="en" keeps the rendered text in English (independent of the
    // route) while useLocalePath still reads the prefix from the URL.
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
      { route: '/ru/explore' },
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    const exploreLink = screen.getByRole('link', { name: 'Explore' });
    expect(exploreLink).toHaveAttribute('href', '/ru/explore');
    expect(exploreLink.className).toMatch(/linkActive/);
    expect(screen.getByRole('link', { name: 'Daily 5' })).toHaveAttribute('href', '/ru');
  });

  it('fires setThemeOverride and closes on a theme option click', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('Dark'));

    expect(getResolvedTheme()).toBe('dark');
    expect(screen.queryByText('Dark')).not.toBeInTheDocument();
  });

  it('renders a caller-supplied navItems override with its own aria-label instead of the default NAV_ITEMS', () => {
    renderWithProviders(
      <MobileMenu
        locale="en"
        onLocaleChange={vi.fn()}
        onLogout={vi.fn()}
        navItems={[{ route: '/organizer/dashboard', labelKey: 'organizer_dashboard_title' }]}
        navAriaLabelKey="organizer_dashboard_title"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(screen.getByRole('navigation', { name: 'Your events' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Your events' })).toHaveAttribute(
      'href',
      '/organizer/dashboard',
    );
    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();
    expect(screen.queryByText('Explore')).not.toBeInTheDocument();
  });

  it('shows Explore · FAQ · Contact, in that order, in the signed-out nav', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} authed={false} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Explore', 'FAQ', 'Contact']);
    expect(screen.getByRole('link', { name: 'FAQ' })).toHaveAttribute('href', '/faq');
  });

  it('keeps the locale prefix on the signed-out FAQ link', () => {
    renderWithProviders(
      <MobileMenu locale="ru" onLocaleChange={vi.fn()} authed={false} />,
      { route: '/ru/explore' },
    );

    fireEvent.click(screen.getByRole('button', { name: 'Меню' }));

    expect(screen.getByRole('link', { name: 'Вопросы и ответы' })).toHaveAttribute('href', '/ru/faq');
  });

  it('shows Daily 5 · Explore · Saved in the signed-in nav; Settings and Contact sit in the account block', () => {
    renderWithProviders(
      <MobileMenu
        locale="en"
        onLocaleChange={vi.fn()}
        onLogout={vi.fn()}
        accountItems={[
          { route: '/settings', labelKey: 'nav_settings' },
          { route: '/contact', labelKey: 'nav_contact' },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Daily 5', 'Explore', 'Saved']);
    expect(screen.queryByText('FAQ')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/contact');
  });

  it('fetches the identity when the drawer opens and shows it in the account block', async () => {
    renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(await screen.findByText('ada@example.com')).toBeInTheDocument();
    expect(screen.getByText('Signed in as')).toBeInTheDocument();
  });

  it('signed out: no Sign in link (the bar shows it), no Sign out, only Explore/FAQ/Contact in nav', () => {
    renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} authed={false} />);

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument();
    expect(screen.queryByText('Sign out')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Explore' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', '/contact');
    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();
    expect(screen.queryByText('Saved')).not.toBeInTheDocument();
    expect(screen.getByText('ET')).toBeInTheDocument();
  });

  it('focuses the first nav item on open, never the search field', async () => {
    renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} showSearch />);

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(screen.getByRole('link', { name: 'Daily 5' })).toHaveFocus();
    expect(screen.getByRole('searchbox')).not.toHaveFocus();
  });

  it('locks page scroll while open and releases it on close; Escape returns focus to the hamburger', async () => {
    renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);
    const hamburger = screen.getByRole('button', { name: 'Menu' });

    await userEvent.click(hamburger);
    expect(document.body.style.overflow).toBe('hidden');

    await userEvent.keyboard('{Escape}');
    expect(document.body.style.overflow).not.toBe('hidden');
    expect(hamburger).toHaveFocus();
  });

  it('renders the search field only when showSearch is set', () => {
    const { unmount } = renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    unmount();

    renderWithProviders(<MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} showSearch />);
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByRole('searchbox')).toHaveAttribute('maxlength', '200');
  });
});
