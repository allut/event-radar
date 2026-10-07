import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import Faq from './Faq';
import { renderWithProviders } from '../../test/utils';
import { t } from '../../i18n';
import enDoc from '../../content/faq/faq.en';
import etDoc from '../../content/faq/faq.et';
import ruDoc from '../../content/faq/faq.ru';
import type { SeoMetaResult } from '../../hooks/useSeoMeta';

// Reconfigurable loaders (vi.hoisted so the vi.mock factory can reference them).
// `loaders` holds the stable vi.fn()s; `mockedLoaderMap` is the FAQ_LOADERS the
// route sees, re-synced from `loaders` before each test so one can drop a locale.
const { loaders, mockedLoaderMap } = vi.hoisted(() => {
  const fns = {
    en: vi.fn(() => Promise.resolve({ default: null as unknown })),
    et: vi.fn(() => Promise.resolve({ default: null as unknown })),
    ru: vi.fn(() => Promise.resolve({ default: null as unknown })),
  };
  return { loaders: fns, mockedLoaderMap: { ...fns } as Partial<typeof fns> };
});

vi.mock('../../content/faq/loaders', () => ({ FAQ_LOADERS: mockedLoaderMap }));

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  getStoredLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
  isAuthenticated: vi.fn(() => false),
  subscribeAuth: vi.fn(() => () => {}),
  subscribeLocale: vi.fn(() => () => {}),
}));

vi.mock('../../components/TopBar', () => ({ default: () => null }));

// Exposes the useSeoMeta result as plain attributes — react-helmet-async's
// head writes are async and SeoTags is a thin render shell (see its comment).
vi.mock('../../components/SeoTags', () => ({
  default: ({ meta }: { meta: SeoMetaResult }) => (
    <div
      data-testid="seo"
      data-title={meta.title}
      data-robots={meta.metaTags.find((tag) => tag.name === 'robots')?.content}
      data-canonical={meta.links.find((link) => link.rel === 'canonical')?.href ?? ''}
      data-xdefault={meta.links.find((link) => link.hrefLang === 'x-default')?.href ?? ''}
      data-hreflangs={meta.links
        .filter((link) => link.hrefLang)
        .map((link) => link.hrefLang)
        .join(',')}
    />
  ),
}));

const FAQ_PATTERNS = { prefixed: '/:locale/faq', bare: '/faq' };

function renderFaq(route: string) {
  const pathPattern = route.startsWith('/faq') ? FAQ_PATTERNS.bare : FAQ_PATTERNS.prefixed;
  return renderWithProviders(<Faq />, { route, pathPattern });
}

beforeEach(() => {
  loaders.en.mockReset().mockResolvedValue({ default: enDoc });
  loaders.et.mockReset().mockResolvedValue({ default: etDoc });
  loaders.ru.mockReset().mockResolvedValue({ default: ruDoc });
  Object.assign(mockedLoaderMap, loaders);
});

describe('Faq', () => {
  it('shows the loading state, then the doc', async () => {
    renderFaq('/en/faq');

    // Loading spinner is labelled with the short nav title.
    expect(screen.getByLabelText('FAQ')).toBeInTheDocument();

    expect(
      await screen.findByRole('heading', { level: 1, name: enDoc.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(enDoc.lede)).toBeInTheDocument();
    const jumpNav = screen.getByRole('navigation', { name: enDoc.jumpNavLabel });
    expect(within(jumpNav).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
      '#about',
      '#event-goers',
      '#organizers',
    ]);
  });

  it('renders three sections and 20 questions, all closed, answers in the DOM', async () => {
    const { container } = renderFaq('/en/faq');
    await screen.findByRole('heading', { level: 1, name: enDoc.title });

    expect(container.querySelectorAll('section[id]')).toHaveLength(3);
    const details = container.querySelectorAll('details');
    expect(details).toHaveLength(20);
    details.forEach((item) => {
      expect(item).not.toHaveAttribute('open');
      // No `name`: several items can be open at once.
      expect(item).not.toHaveAttribute('name');
    });
    // A closed answer is still rendered, with its "Link to this answer" link.
    const free = container.querySelector('details#is-it-free') as HTMLElement;
    expect(within(free).getByText(/nobody can pay to be shown higher/)).toBeInTheDocument();
    expect(within(free).getByRole('link', { name: enDoc.answerLinkLabel, hidden: true })).toHaveAttribute(
      'href',
      '#is-it-free',
    );
  });

  it('renders the Estonian doc on the bare /faq path', async () => {
    renderFaq('/faq');

    expect(
      await screen.findByRole('heading', { level: 1, name: etDoc.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(etDoc.lede)).toBeInTheDocument();
    expect(loaders.et).toHaveBeenCalled();
    expect(loaders.en).not.toHaveBeenCalled();
  });

  it('renders the Russian doc on /ru/faq', async () => {
    renderFaq('/ru/faq');

    expect(
      await screen.findByRole('heading', { level: 1, name: ruDoc.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(ruDoc.lede)).toBeInTheDocument();
    expect(loaders.ru).toHaveBeenCalled();
    expect(loaders.en).not.toHaveBeenCalled();
  });

  it('keeps the locale prefix on internal links under /ru/faq', async () => {
    const { container } = renderFaq('/ru/faq');
    await screen.findByRole('heading', { level: 1, name: ruDoc.title });

    const deleteAccount = container.querySelector('details#delete-account') as HTMLElement;
    expect(
      within(deleteAccount).getByRole('link', { name: 'Политике конфиденциальности', hidden: true }),
    ).toHaveAttribute('href', '/ru/privacy');
    expect(
      within(deleteAccount).getByRole('link', { name: 'contact@eventradar.ee', hidden: true }),
    ).toHaveAttribute('href', 'mailto:contact@eventradar.ee');
    expect(screen.getByRole('link', { name: ruDoc.contact.cta })).toHaveAttribute('href', '/ru/contact');
  });

  it('falls back to the English doc when the active locale chunk fails', async () => {
    loaders.ru.mockRejectedValue(new Error('chunk load failed'));
    renderFaq('/ru/faq');

    expect(
      await screen.findByRole('heading', { level: 1, name: enDoc.title }),
    ).toBeInTheDocument();
    expect(loaders.ru).toHaveBeenCalled();
    expect(loaders.en).toHaveBeenCalled();
  });

  it('shows the error state when the English fallback fails too', async () => {
    loaders.ru.mockRejectedValue(new Error('chunk load failed'));
    loaders.en.mockRejectedValue(new Error('chunk load failed'));
    renderFaq('/ru/faq');

    expect(await screen.findByText(t('generic_error', 'ru'))).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
  });

  it('tries English once when the locale has no chunk of its own, then errors', async () => {
    delete mockedLoaderMap.et;
    loaders.en.mockRejectedValue(new Error('chunk load failed'));
    renderFaq('/faq'); // bare path → Estonian, with its loader dropped

    expect(await screen.findByText(t('generic_error', 'et'))).toBeInTheDocument();
    expect(loaders.en).toHaveBeenCalledTimes(1);
  });

  it('is noindex before the doc loads, then index, follow with canonical and hreflang', async () => {
    renderFaq('/faq');

    const seo = screen.getByTestId('seo');
    expect(seo).toHaveAttribute('data-robots', 'noindex');
    expect(seo).toHaveAttribute('data-canonical', '');

    await screen.findByRole('heading', { level: 1, name: etDoc.title });
    expect(seo).toHaveAttribute('data-robots', 'index, follow');
    expect(seo).toHaveAttribute('data-canonical', 'https://eventradar.ee/faq');
    expect(seo).toHaveAttribute('data-hreflangs', 'et,en,ru,x-default');
    expect(seo).toHaveAttribute('data-xdefault', 'https://eventradar.ee/faq');
    expect(seo.getAttribute('data-title')).toMatch(/^Korduma kippuvad küsimused \| /);
  });
});
