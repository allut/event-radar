import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LegalPage from './LegalPage';
import { renderWithProviders } from '../../test/utils';
import type { LegalDoc } from '../../content/legal/types';

const enDoc: LegalDoc = {
  title: 'Privacy Policy',
  lastUpdated: '2026-07-24',
  intro: [{ kind: 'p', content: ['Intro paragraph.'] }],
  sections: [
    {
      heading: '1. Contact',
      blocks: [
        {
          kind: 'ul',
          items: [
            ['A plain bullet.'],
            [{ text: 'contact@whatsonradar.com', href: 'mailto:contact@whatsonradar.com' }],
          ],
        },
      ],
    },
  ],
};

const etDoc: LegalDoc = {
  title: 'Privaatsuspoliitika',
  lastUpdated: '2026-07-24',
  intro: [],
  sections: [{ heading: '1. Kontakt', blocks: [{ kind: 'p', content: ['Eesti sisu.'] }] }],
};

// Reconfigurable loaders (vi.hoisted so the vi.mock factory can reference them).
const loaders = vi.hoisted(() => {
  const en = vi.fn(() => Promise.resolve({ default: null as unknown }));
  const et = vi.fn(() => Promise.resolve({ default: null as unknown }));
  return { en, et };
});

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
  clearSignedInHint: vi.fn(),
  beginLogout: vi.fn(),
  isAuthenticated: vi.fn(() => false),
  subscribeAuth: vi.fn(() => () => {}),
  subscribeLocale: vi.fn(() => () => {}),
}));

// Deterministic TopBar stub exposing a locale-switch trigger, so the test drives
// onLocaleChange without depending on LocaleSelector internals.
vi.mock('../TopBar', () => ({
  default: ({ onLocaleChange }: { onLocaleChange: (c: string) => void }) => (
    <button data-testid="switch-et" onClick={() => onLocaleChange('et')}>
      switch
    </button>
  ),
}));

vi.mock('../../content/legal', () => ({
  LEGAL_LOADERS: {
    privacy: { en: loaders.en, et: loaders.et, ru: loaders.en },
    terms: { en: loaders.en, et: loaders.et, ru: loaders.en },
  },
}));

beforeEach(() => {
  loaders.en.mockReset().mockResolvedValue({ default: enDoc });
  loaders.et.mockReset().mockResolvedValue({ default: etDoc });
});

describe('LegalPage', () => {
  it('shows the loading state, then renders the doc structure', async () => {
    renderWithProviders(<LegalPage docId="privacy" titleKey="privacy_title" />);

    // Loading spinner uses the localized short title as its aria-label.
    expect(screen.getByLabelText('Privacy')).toBeInTheDocument();

    // After the lazy loader resolves, the full doc renders.
    const heading = await screen.findByRole('heading', { level: 1, name: 'Privacy Policy' });
    expect(heading).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: '1. Contact' })).toBeInTheDocument();
    expect(screen.getByText('Last updated 2026-07-24')).toBeInTheDocument();

    // Bullet list with an inline mailto link.
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(1);
    const link = screen.getByRole('link', { name: 'contact@whatsonradar.com' });
    expect(link).toHaveAttribute('href', 'mailto:contact@whatsonradar.com');
  });

  it('swaps the loaded doc when the locale changes', async () => {
    renderWithProviders(<LegalPage docId="privacy" titleKey="privacy_title" />);
    await screen.findByRole('heading', { level: 1, name: 'Privacy Policy' });

    await userEvent.click(screen.getByTestId('switch-et'));

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Privaatsuspoliitika' }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('heading', { level: 1, name: 'Privacy Policy' }),
    ).not.toBeInTheDocument();
  });

  it('renders an error state when the chunk (and its fallback) fail to load', async () => {
    // locale is 'en' (== fallback), so a single rejection exhausts both paths.
    loaders.en.mockRejectedValue(new Error('chunk load failed'));
    renderWithProviders(<LegalPage docId="privacy" titleKey="privacy_title" />);

    expect(await screen.findByText('Something went wrong. Please try again.')).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { level: 1, name: 'Privacy Policy' }),
    ).not.toBeInTheDocument();
  });
});
