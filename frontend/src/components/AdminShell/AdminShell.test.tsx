import { describe, it, expect, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import AdminShell from './AdminShell';

describe('AdminShell', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('renders the theme toggle next to Sign out in the foot area', () => {
    renderWithProviders(<AdminShell>content</AdminShell>);
    expect(screen.getByRole('button', { name: 'Light' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out →' })).toBeInTheDocument();
  });
});
