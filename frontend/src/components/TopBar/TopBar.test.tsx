import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, LocationProbe } from '../../test/utils';
import TopBar from './TopBar';

vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  organizerApi: { get: vi.fn() },
}));

import { api } from '../../api/client';

const mockGet = vi.mocked(api.get);

// jsdom applies no media queries, so desktop and phone variants are both in the
// DOM; assertions on shared controls use getAll*.
function scrollTo(y: number) {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
  act(() => {
    window.dispatchEvent(new Event('scroll'));
  });
}

beforeEach(() => {
  scrollTo(0);
  mockGet.mockReset();
  mockGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/public/counts')) return { today_count: 0 };
    if (path === '/auth/me') return { email: 'ada@example.com' };
    return undefined;
  });
});

describe('TopBar signed out', () => {
  it('shows Explore · FAQ · Contact, a Sign in link, no account menu, and the preferences menu', () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Explore', 'FAQ', 'Contact']);
    expect(screen.getByRole('link', { name: 'FAQ' })).toHaveAttribute('href', '/faq');
    expect(screen.getAllByRole('link', { name: 'Sign in' })[0]).toHaveAttribute('href', '/login');
    expect(screen.queryByRole('button', { name: 'Account' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Language and theme' })).toHaveTextContent('EN');
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
  });

  it('keeps the locale prefix on the nav and Sign in links', () => {
    renderWithProviders(<TopBar locale="ru" onLocaleChange={vi.fn()} authed={false} />, { route: '/ru/explore' });

    expect(screen.getByRole('link', { name: 'Вопросы и ответы' })).toHaveAttribute('href', '/ru/faq');
    expect(screen.getAllByRole('link', { name: 'Войти' })[0]).toHaveAttribute('href', '/ru/login');
  });

  it('shows Back alongside Sign in when onBack is given', () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} onBack={vi.fn()} />);

    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /sign in/i }).length).toBeGreaterThan(0);
  });

  it('offers Sign in as the phone primary action; the drawer does not repeat it', async () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    const before = screen.getAllByRole('link', { name: 'Sign in' }).length;

    await userEvent.click(screen.getByRole('button', { name: 'Menu' }));

    expect(screen.getAllByRole('link', { name: 'Sign in' })).toHaveLength(before);
  });
});

describe('TopBar signed in', () => {
  const renderSignedIn = (props = {}) =>
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} authed {...props} />);

  it('shows Daily 5 · Explore · Saved, an account menu and no Sign in link', () => {
    renderSignedIn();

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Daily 5', 'Explore', 'Saved']);
    expect(screen.queryByRole('link', { name: 'FAQ' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /sign in/i })).not.toBeInTheDocument();
  });

  it('hides the nav but keeps the account menu and hamburger when showNav is false', () => {
    renderSignedIn({ showNav: false });

    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument();
  });

  it('does not fetch the identity until the account menu opens', async () => {
    renderSignedIn();
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/public/counts')));
    expect(mockGet).not.toHaveBeenCalledWith('/auth/me');

    await userEvent.click(screen.getByRole('button', { name: 'Account' }));

    expect(await screen.findByText('ada@example.com')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/auth/me');
  });

  it('puts Settings and Contact in the account menu, and Sign out calls onLogout', async () => {
    const onLogout = vi.fn();
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} onLogout={onLogout} authed />);

    await userEvent.click(screen.getByRole('button', { name: 'Account' }));

    expect(screen.getByRole('menu')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Settings' })).toHaveAttribute('href', '/settings');
    expect(screen.getByRole('menuitem', { name: 'Contact' })).toHaveAttribute('href', '/contact');
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('offers search, not Sign in, as the phone primary action — unless showSearch is false', () => {
    const { unmount } = renderSignedIn();
    // Wide field + narrow popover + phone popover.
    expect(screen.getAllByRole('search')).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Search events…' })).toHaveLength(2);
    unmount();

    renderSignedIn({ showSearch: false });
    expect(screen.queryByRole('search')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Search events…' })).not.toBeInTheDocument();
  });
});

describe('TopBar search', () => {
  it('submits to /explore?q= under the locale prefix and caps the query length', async () => {
    renderWithProviders(
      <>
        <TopBar locale="ru" onLocaleChange={vi.fn()} authed={false} />
        <LocationProbe />
      </>,
      { route: '/ru/faq' },
    );
    const input = screen.getByRole('searchbox');
    expect(input).toHaveAttribute('maxlength', '200');

    await userEvent.type(input, 'джаз ночь{Enter}');

    expect(screen.getByTestId('location-probe')).toHaveTextContent(
      `/ru/explore?q=${encodeURIComponent('джаз ночь')}`,
    );
  });

  it('opens the same field in a popover from the icon button and closes it on Escape', async () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    const [icon] = screen.getAllByRole('button', { name: 'Search events…' });

    await userEvent.click(icon);
    expect(icon).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByRole('searchbox')).toHaveLength(2);

    await userEvent.keyboard('{Escape}');
    expect(icon).toHaveAttribute('aria-expanded', 'false');
    expect(icon).toHaveFocus();
  });
});

describe('TopBar pulse chip', () => {
  it('renders the today count linking to /explore?date=today', async () => {
    mockGet.mockImplementation(async () => ({ today_count: 37 }));
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);

    const chip = await screen.findByRole('link', { name: /on today/i });
    expect(chip).toHaveTextContent('37 on today');
    expect(chip).toHaveAttribute('href', '/explore?date=today');
  });

  it('is hidden at zero, and hidden when showPulse is false', async () => {
    const { unmount } = renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByRole('link', { name: /on today/i })).not.toBeInTheDocument();
    unmount();

    mockGet.mockClear();
    mockGet.mockImplementation(async () => ({ today_count: 5 }));
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} showPulse={false} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockGet).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: /on today/i })).not.toBeInTheDocument();
  });

  it('uses the Estonian copy "täna {count}"', async () => {
    mockGet.mockImplementation(async () => ({ today_count: 12 }));
    renderWithProviders(<TopBar locale="et" onLocaleChange={vi.fn()} authed={false} />);

    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'täna 12' })).toBeInTheDocument();
  });
});

describe('TopBar preferences menu', () => {
  it('opens a dialog with the current locale pressed, and changes locale', async () => {
    const onLocaleChange = vi.fn();
    renderWithProviders(<TopBar locale="en" onLocaleChange={onLocaleChange} authed={false} />);

    await userEvent.click(screen.getByRole('button', { name: 'Language and theme' }));

    const dialog = screen.getByRole('dialog', { name: 'Language and theme' });
    expect(within(dialog).getByRole('button', { name: 'EN' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(dialog).getByRole('button', { name: 'ET' })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(within(dialog).getByRole('button', { name: 'ET' }));
    expect(onLocaleChange).toHaveBeenCalledWith('et');
  });

  it('sets a theme override and marks the pressed theme; the trigger glyph is theme-independent', async () => {
    const spy = vi.spyOn(await import('../../lib/theme'), 'setThemeOverride');
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    const trigger = screen.getByRole('button', { name: 'Language and theme' });
    const glyphBefore = trigger.querySelector('svg')?.outerHTML;

    await userEvent.click(trigger);
    const group = screen.getByRole('group', { name: 'Theme' });
    const other = within(group).getAllByRole('button').find((b) => b.getAttribute('aria-pressed') === 'false')!;
    await userEvent.click(other);

    expect(spy).toHaveBeenCalled();
    expect(trigger.querySelector('svg')?.outerHTML).toBe(glyphBefore);
    spy.mockRestore();
  });
});

describe('TopBar condense and transparency', () => {
  it('condenses past 24px and expands again only under 4px (hysteresis)', () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    const bar = screen.getByRole('banner');
    expect(bar).not.toHaveAttribute('data-condensed');

    scrollTo(20);
    expect(bar).not.toHaveAttribute('data-condensed');
    scrollTo(30);
    expect(bar).toHaveAttribute('data-condensed');
    scrollTo(10); // between the thresholds: stays condensed
    expect(bar).toHaveAttribute('data-condensed');
    scrollTo(3);
    expect(bar).not.toHaveAttribute('data-condensed');
  });

  it('is transparent only while unscrolled and when asked to be', () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} transparent />);
    const bar = screen.getByRole('banner');
    expect(bar).toHaveAttribute('data-transparent');

    scrollTo(40);
    expect(bar).not.toHaveAttribute('data-transparent');
  });

  it('is never transparent unless asked', () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} authed={false} />);
    expect(screen.getByRole('banner')).not.toHaveAttribute('data-transparent');
  });
});

describe('TopBar drawer', () => {
  it('focuses the first nav item on open, locks scroll, and Escape returns focus to the hamburger', async () => {
    renderWithProviders(<TopBar locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} authed />);
    const hamburger = screen.getByRole('button', { name: 'Menu' });

    await userEvent.click(hamburger);

    const [, drawerNav] = screen.getAllByRole('navigation'); // [bar, drawer]
    expect(within(drawerNav).getAllByRole('link')[0]).toHaveFocus();
    expect(document.body.style.overflow).toBe('hidden');
    expect(hamburger).toHaveAttribute('aria-expanded', 'true');

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(hamburger).toHaveFocus());
    expect(document.body.style.overflow).not.toBe('hidden');
  });
});
