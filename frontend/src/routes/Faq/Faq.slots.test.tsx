import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import Faq from './Faq';
import { renderWithProviders } from '../../test/utils';
import { FAQ_PAID_ID_PREFIX, SPONSORED_RANKING_TARGET } from '../../constants/sponsored';

// Real FAQ copy and loaders: pins the paid-slot answers with the flag on and off.
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
vi.mock('../../components/TopBar', () => ({ default: () => null }));
vi.mock('../../components/SeoTags', () => ({ default: () => null }));

const LOCALES = ['en', 'et', 'ru'] as const;
const PAID_IDS = ['paid-on-event-radar', 'paid-change-results', 'paid-chosen', 'paid-in-email', 'paid-data'];

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.unstubAllEnvs());

async function renderFaq(locale: string) {
  state.locale = locale;
  const route = locale === 'et' ? '/faq' : `/${locale}/faq`;
  const view = renderWithProviders(<Faq />, { route, pathPattern: locale === 'et' ? '/faq' : '/:locale/faq' });
  await waitFor(() => expect(view.container.querySelector('details')).not.toBeNull());
  return view;
}

describe.each(LOCALES)('FAQ paid-slot answers (%s)', (locale) => {
  it('adds the five paid-* questions after "email" and rewrites "Is it free?" while the flag is on', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'true');
    const { container } = await renderFaq(locale);
    const ids = [...container.querySelectorAll('details')].map((d) => d.id);
    expect(ids.filter((id) => id.startsWith(FAQ_PAID_ID_PREFIX))).toEqual(PAID_IDS);
    expect(ids.indexOf('paid-on-event-radar')).toBe(ids.indexOf('email') + 1);
    const free = container.querySelector('#is-it-free') as HTMLElement;
    const prefix = locale === 'et' ? '' : `/${locale}`;
    const hrefs = within(free).getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(hrefs).toContain(`${prefix}${SPONSORED_RANKING_TARGET}`);
    expect(container.querySelector('#ads')).toBeNull();
  });

  it('keeps the original "Is it free?" answer and no paid-* question while the flag is off', async () => {
    vi.stubEnv('VITE_PROMOTIONS_SLOTS_ENABLED', 'false');
    const { container } = await renderFaq(locale);
    const ids = [...container.querySelectorAll('details')].map((d) => d.id);
    expect(ids.some((id) => id.startsWith(FAQ_PAID_ID_PREFIX))).toBe(false);
    const free = container.querySelector('#is-it-free') as HTMLElement;
    expect(within(free).queryAllByRole('link').filter((a) => a.getAttribute('href')?.includes('paid-slots'))).toHaveLength(0);
    expect(screen.queryByText(/paid-slots/)).not.toBeInTheDocument();
  });
});
