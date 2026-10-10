import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LocationProbe, renderWithProviders } from '../../test/utils';
import { SearchField, SearchPopover } from './BarSearch';

describe('SearchField', () => {
  it('navigates to /explore?q= (trimmed, encoded) and clears itself', async () => {
    const onDone = vi.fn();
    renderWithProviders(<><SearchField locale="en" onDone={onDone} /><LocationProbe /></>);

    await userEvent.type(screen.getByRole('searchbox'), '  rock & roll {Enter}');

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/explore?q=rock%20%26%20roll');
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(onDone).toHaveBeenCalled();
  });

  it('goes to plain /explore for an empty query', async () => {
    renderWithProviders(<><SearchField locale="en" /><LocationProbe /></>, { route: '/faq' });
    await userEvent.type(screen.getByRole('searchbox'), '{Enter}');
    expect(screen.getByTestId('location-probe')).toHaveTextContent(/^\/explore$/);
  });

  it('labels the field with the Explore placeholder', () => {
    renderWithProviders(<SearchField locale="en" />);
    expect(screen.getByRole('searchbox', { name: 'Search events…' })).toBeInTheDocument();
  });
});

describe('SearchPopover', () => {
  it('focuses the field on open and closes after a submit', async () => {
    renderWithProviders(<SearchPopover locale="en" />);
    const trigger = screen.getByRole('button', { name: 'Search events…' });

    await userEvent.click(trigger);
    expect(screen.getByRole('searchbox')).toHaveFocus();

    await userEvent.type(screen.getByRole('searchbox'), 'jazz{Enter}');
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });
});
