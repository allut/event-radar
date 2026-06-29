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
