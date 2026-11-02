import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import LegalPage from './LegalPage';
import { renderWithProviders } from '../../test/utils';
import { OPERATOR_IDENTITY, OPERATOR_FIELD_LABELS, type OperatorField } from '../../constants/operator';
import { ORGANIZER_TERMS_VERSION } from '../../_generated/sharedConstants';

// Real content, real loaders: these tests pin what the public pages show with
// the Sponsored slots flag on and off, in every locale.
const state = vi.hoisted(() => ({ locale: 'en' }));

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => state.locale),
  getStoredLocale: vi.fn(() => state.locale),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
  isAuthenticated: vi.fn(() => false),
  subscribeAuth: vi.fn(() => () => {}),
}));
vi.mock('../TopBar', () => ({ default: () => null }));

const LOCALES = ['en', 'et', 'ru'] as const;
const scrollIntoView = vi.fn();

beforeEach(() => {
  Element.prototype.scrollIntoView = scrollIntoView;
  scrollIntoView.mockClear();
});
afterEach(() => vi.unstubAllEnvs());

const PATHS = { ranking: 'ranking', privacy: 'privacy', organizerTerms: 'organizer-terms' };
/** The URL's locale prefix, which localePath() follows (Estonian is bare). */
const prefixOf = (locale: string) => (locale === 'et' ? '' : `/${locale}`);

async function renderDoc(docId: keyof typeof PATHS, locale: string, hash = '') {
  const route = `${prefixOf(locale)}/${PATHS[docId]}${hash}`;
  state.locale = locale;
  const view = renderWithProviders(<LegalPage docId={docId} titleKey="ranking_link" />, { route });
  await waitFor(() => expect(view.container.querySelector('h1')).not.toBeNull());
  return view;
}

describe.each(LOCALES)('Ranking disclosure (%s)', (locale) => {
  it('has the #paid-slots section while the slots flag is on', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'true');
    const { container } = await renderDoc('ranking', locale);
    const section = container.querySelector('#paid-slots');
    expect(section).not.toBeNull();
    expect(section?.querySelector('h2')).not.toBeNull();
    expect(container.querySelector('#ads')).toBeNull();
    // The section links on to the Privacy notice, locale-prefixed.
    const prefix = prefixOf(locale);
    const links = within(section as HTMLElement).getAllByRole('link');
    expect(links.some((a) => a.getAttribute('href') === `${prefix}/privacy`)).toBe(true);
  });

  it('has no paid-slots section while the flag is off', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'false');
    const { container } = await renderDoc('ranking', locale);
    expect(container.querySelector('#paid-slots')).toBeNull();
    expect(container.querySelector('#organizers')).not.toBeNull();
  });

  it('scrolls to #paid-slots when the link is followed', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'true');
    await renderDoc('ranking', locale, '#paid-slots');
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(scrollIntoView.mock.contexts[0]).toHaveProperty('id', 'paid-slots');
  });
});

describe.each(LOCALES)('Privacy notice (%s)', (locale) => {
  it('adds the ads copy only while the flag is on, with a date never older, keeping the numbering', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'false');
    const off = await renderDoc('privacy', locale);
    const offHeadings = [...off.container.querySelectorAll('h2')].map((h) => h.textContent);
    const offItems = off.container.querySelectorAll('li').length;
    const offParas = off.container.querySelectorAll('p').length;
    const offDate = off.container.querySelector('p')?.textContent;
    off.unmount();

    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'true');
    const on = await renderDoc('privacy', locale);
    expect([...on.container.querySelectorAll('h2')].map((h) => h.textContent)).toEqual(offHeadings);
    expect(on.container.querySelectorAll('li').length).toBeGreaterThan(offItems);
    expect(on.container.querySelectorAll('p').length).toBeGreaterThanOrEqual(offParas);
    const isoDate = (text: string | null | undefined) => text?.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? '';
    const onDate = on.container.querySelector('p')?.textContent;
    expect(isoDate(offDate)).not.toBe('');
    expect(isoDate(onDate) >= isoDate(offDate)).toBe(true);
  });
});

describe.each(LOCALES)('Organizer terms page (%s)', (locale) => {
  it('shows the DRAFT notice, the version and a visible placeholder per unfilled field', async () => {
    const { container } = await renderDoc('organizerTerms', locale);
    expect(container.querySelector('[role="note"]')).not.toBeNull();
    expect(container.textContent).toContain(String(ORGANIZER_TERMS_VERSION));
    const fields = new Set([...container.querySelectorAll('mark[data-operator-field]')].map((m) => m.getAttribute('data-operator-field')));
    expect([...fields].sort()).toEqual(Object.keys(OPERATOR_IDENTITY).sort());
    const first = container.querySelector('mark[data-operator-field="registryCode"]');
    expect(first?.textContent).toBe(`⟨${OPERATOR_FIELD_LABELS.registryCode[locale]}⟩`);
  });

  it('links the Ranking disclosure with the current locale prefix', async () => {
    const { container } = await renderDoc('organizerTerms', locale);
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(hrefs).toContain(`${prefixOf(locale)}/ranking`);
  });

  it('renders a filled field as plain text, with no placeholder', async () => {
    const identity = OPERATOR_IDENTITY as Record<OperatorField, string | null>;
    identity.registryCode = '12345678';
    try {
      const { container } = await renderDoc('organizerTerms', locale);
      expect(container.querySelector('mark[data-operator-field="registryCode"]')).toBeNull();
      expect(container.textContent).toContain('12345678');
    } finally {
      identity.registryCode = null;
    }
  });
});

describe('Organizer terms page chrome', () => {
  it('has no draft notice on the other legal pages', async () => {
    const { container } = await renderDoc('ranking', 'en');
    expect(container.querySelector('[role="note"]')).toBeNull();
    expect(screen.queryByText('Draft for legal review')).not.toBeInTheDocument();
  });
});
