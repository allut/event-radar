import { t } from '../../i18n';
import { describe, it, expect } from 'vitest';
import { StatusCodes } from 'http-status-codes';
import { screen } from '@testing-library/react';
import NotFound from './NotFound';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
}));

describe('NotFound', () => {
  it('renders 404 code', () => {
    renderWithProviders(<NotFound />);
    expect(screen.getByText(String(StatusCodes.NOT_FOUND))).toBeInTheDocument();
  });

  it('renders back link to /', () => {
    renderWithProviders(<NotFound />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/');
  });
});

describe('NotFound locale', () => {
  // The page speaks the URL's language (like the Footer under it, #497) —
  // never the saved preference, mocked to 'en' above.
  it('renders in the URL prefix\'s language', () => {
    renderWithProviders(<NotFound />, { route: '/ru/no-such-page' });
    expect(screen.getAllByText(t('not_found_title', 'ru')).length).toBeGreaterThan(0);
  });

  it('renders Estonian on a bare path', () => {
    renderWithProviders(<NotFound />, { route: '/no-such-page' });
    expect(screen.getAllByText(t('not_found_title', 'et')).length).toBeGreaterThan(0);
  });
});
