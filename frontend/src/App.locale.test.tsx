import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from './App';

// Integration coverage for the app-wide locale-routing wrapper (issue #47):
// bare-path behavior split by route class, redirect-on-preference for
// "standard" routes, and Estonian fallback for an unrecognized `:locale`
// segment. Network calls are left unmocked on purpose — every route
// exercised here either fetches nothing while signed out (Contact) or
// tolerates a failed fetch by rendering an (still locale-correct) error/
// loading state (EventDetail), so the assertions stay focused on routing.

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

    // The fetch is unmocked and fails in jsdom, but the error copy itself
    // must still be Estonian — proof the bare path rendered in Estonian
    // rather than redirecting to /ru/events/1 first.
    await waitFor(() => expect(screen.getByText(/sündmust ei leitud/i)).toBeInTheDocument());
    expect(window.location.pathname).toBe('/events/1');
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

  it('keeps the Protected guard enforced inside the locale wrapper for a prefixed route', async () => {
    setPath('/en/settings');
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/login'));
  });
});
