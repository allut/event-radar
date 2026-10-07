import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

// Every request fails like an unreachable backend: the routes exercised here
// render a (still guard/locale-correct) error or loading state, so assertions
// stay focused on routing.
vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/client')>();
  const { NETWORK_ERROR_CODE } = await import('./constants');
  const fail = () => Promise.reject(new actual.ApiError(0, 'network error', NETWORK_ERROR_CODE));
  const failing = { get: fail, post: fail, patch: fail, delete: fail };
  return { ...actual, api: failing, organizerApi: failing, adminApi: failing };
});

// Integration coverage for the app-wide locale-routing wrapper (issue #47):
// bare-path behavior split by route class, redirect-on-preference for
// "standard" routes, and Estonian fallback for an unrecognized `:locale`
// segment. The api module is mocked to reject — every route exercised here
// either fetches nothing while signed out (Contact) or tolerates a failed
// fetch by rendering an (still locale-correct) error/loading state
// (EventDetail), so the assertions stay focused on routing.

function setPath(path: string) {
  window.history.pushState(null, '', path);
}

beforeEach(() => {
  localStorage.clear();
  setPath('/');
});

describe('App locale-routing wrapper', () => {
  it('never redirects the bare public Home route, even with a stored non-Estonian preference', async () => {
    localStorage.setItem('locale', 'ru');
    setPath('/');
    render(<App />);

    await waitFor(() => expect(screen.getByRole('link', { name: 'Logi sisse' })).toBeInTheDocument());
    expect(window.location.pathname).toBe('/');
  });

  it('never redirects the bare public EventDetail route, even with a stored non-Estonian preference', async () => {
    localStorage.setItem('locale', 'ru');
    setPath('/events/1');
    render(<App />);

    // The (mocked) fetch fails, but the error copy itself
    // must still be Estonian — proof the bare path rendered in Estonian
    // rather than redirecting to /ru/events/1 first.
    await waitFor(() => expect(screen.getByText(/sündmust ei leitud/i)).toBeInTheDocument());
    expect(window.location.pathname).toBe('/events/1');
  });

  it('never redirects the bare public Faq route, even with a stored non-Estonian preference', async () => {
    localStorage.setItem('locale', 'ru');
    setPath('/faq');
    render(<App />);

    // The bare path stays bare and renders Estonian, not the stored Russian.
    expect(await screen.findByRole('heading', { level: 1, name: 'Korduma kippuvad küsimused' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/faq');
  });

  it('redirects a bare standard route to the stored non-Estonian preference', async () => {
    localStorage.setItem('locale', 'ru');
    setPath('/contact');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/ru/contact'));
    expect(screen.getByRole('heading', { name: 'Контакты' })).toBeInTheDocument();
  });

  it('does not redirect a bare standard route when the stored preference is already Estonian', async () => {
    localStorage.setItem('locale', 'et');
    setPath('/contact');
    render(<App />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument());
    expect(window.location.pathname).toBe('/contact');
  });

  it('renders Estonian (not the en/localStorage UI default) for a first-time visitor on a bare standard route', async () => {
    setPath('/contact');
    render(<App />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument());
    expect(window.location.pathname).toBe('/contact');
  });

  it('falls back to Estonian for an unrecognized :locale segment without redirecting the URL', async () => {
    setPath('/xx/contact');
    render(<App />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument());
    expect(window.location.pathname).toBe('/xx/contact');
  });

  it('reaches every route under both its bare and locale-prefixed form', async () => {
    setPath('/en/contact');
    render(<App />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Contact' })).toBeInTheDocument());
  });

  it('keeps the Protected guard enforced inside the locale wrapper for a prefixed route, carrying the locale prefix into the redirect', async () => {
    setPath('/en/settings');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/en/login'));
  });

  it('switching to Estonian from a prefixed route lands on the bare path with no bounce back to the prefix', async () => {
    localStorage.setItem('locale', 'ru');
    setPath('/ru/contact');
    render(<App />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Контакты' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'RU' }));
    await userEvent.click(screen.getByRole('button', { name: 'ET' }));

    await waitFor(() => expect(window.location.pathname).toBe('/contact'));
    expect(screen.getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument();
  });

  it('carries the locale prefix into Footer links on a prefixed route', async () => {
    // Footer's own display locale comes from useLocale() (localStorage), not
    // the URL — independent of the page's locale — so with no stored
    // preference it renders its English strings even under a /ru/ route;
    // only the href prefixing (from useLocalePath, URL-driven) is under test.
    setPath('/ru/contact');
    render(<App />);

    await waitFor(() => expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/ru/privacy'));
  });
});
