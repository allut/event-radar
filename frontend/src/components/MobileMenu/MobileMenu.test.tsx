import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import MobileMenu from './MobileMenu';

describe('MobileMenu', () => {
  it('toggles the popover on trigger click', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByText('Daily 5')).toBeInTheDocument();
  });

  it('navigates and closes on a nav link click', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('Explore'));

    expect(screen.queryByText('Explore')).not.toBeInTheDocument();
  });

  it('fires onLocaleChange and closes on a locale click', () => {
    const onLocaleChange = vi.fn();
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={onLocaleChange} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('ET'));

    expect(onLocaleChange).toHaveBeenCalledWith('et');
    expect(screen.queryByText('ET')).not.toBeInTheDocument();
  });

  it('fires onLogout and closes on sign out click', () => {
    const onLogout = vi.fn();
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={onLogout} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    fireEvent.click(screen.getByText('Sign out'));

    expect(onLogout).toHaveBeenCalled();
    expect(screen.queryByText('Sign out')).not.toBeInTheDocument();
  });

  it('closes on Escape', () => {
    renderWithProviders(
      <MobileMenu locale="en" onLocaleChange={vi.fn()} onLogout={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByText('Daily 5')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('Daily 5')).not.toBeInTheDocument();
  });
});
