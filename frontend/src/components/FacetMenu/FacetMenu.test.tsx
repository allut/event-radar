import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FacetMenu from './FacetMenu';

const options = [
  { value: 'music', label: 'Music' },
  { value: 'theater', label: 'Theatre' },
];

describe('FacetMenu', () => {
  it('opens the popover and shows options on trigger click', async () => {
    render(<FacetMenu label="Category" options={options} selected={[]} onToggle={vi.fn()} ariaLabel="Categories" />);
    expect(screen.queryByRole('button', { name: 'Music' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Category/ }));
    expect(screen.getByRole('button', { name: 'Music' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Theatre' })).toBeInTheDocument();
  });

  it('fires onToggle when an option is clicked', async () => {
    const onToggle = vi.fn();
    render(<FacetMenu label="Category" options={options} selected={[]} onToggle={onToggle} ariaLabel="Categories" />);
    await userEvent.click(screen.getByRole('button', { name: /Category/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Music' }));
    expect(onToggle).toHaveBeenCalledWith('music');
  });

  it('closes on Escape', async () => {
    render(<FacetMenu label="Category" options={options} selected={[]} onToggle={vi.fn()} ariaLabel="Categories" />);
    await userEvent.click(screen.getByRole('button', { name: /Category/ }));
    expect(screen.getByRole('button', { name: 'Music' })).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Music' })).not.toBeInTheDocument();
  });

  it('closes on outside click', async () => {
    render(
      <div>
        <button type="button">outside</button>
        <FacetMenu label="Category" options={options} selected={[]} onToggle={vi.fn()} ariaLabel="Categories" />
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Category/ }));
    expect(screen.getByRole('button', { name: 'Music' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('button', { name: 'Music' })).not.toBeInTheDocument();
  });

  it('shows the active selection count on the trigger', () => {
    render(<FacetMenu label="Category" options={options} selected={['music', 'theater']} onToggle={vi.fn()} ariaLabel="Categories" />);
    expect(screen.getByRole('button', { name: 'Category · 2' })).toBeInTheDocument();
  });
});
