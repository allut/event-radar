import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SelectMenu from './SelectMenu';

const options = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'date', label: 'Date' },
  { value: 'price', label: 'Price' },
];

describe('SelectMenu', () => {
  it('shows the current value on the trigger', () => {
    render(<SelectMenu label="Sort by" value="relevance" options={options} onChange={vi.fn()} ariaLabel="Sort by" />);
    expect(screen.getByRole('button', { name: 'Sort by Relevance' })).toBeInTheDocument();
  });

  it('opens the popover with a vertical option list on trigger click', async () => {
    render(<SelectMenu label="Sort by" value="relevance" options={options} onChange={vi.fn()} ariaLabel="Sort by" />);
    expect(screen.queryByRole('button', { name: 'Date' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Sort by Relevance' }));
    expect(screen.getByRole('button', { name: 'Date' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Price' })).toBeInTheDocument();
  });

  it('fires onChange and closes when an option is clicked', async () => {
    const onChange = vi.fn();
    render(<SelectMenu label="Sort by" value="relevance" options={options} onChange={onChange} ariaLabel="Sort by" />);
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Relevance' }));
    await userEvent.click(screen.getByRole('button', { name: 'Date' }));
    expect(onChange).toHaveBeenCalledWith('date');
    expect(screen.queryByRole('button', { name: 'Price' })).not.toBeInTheDocument();
  });

  it('closes on Escape', async () => {
    render(<SelectMenu label="Sort by" value="relevance" options={options} onChange={vi.fn()} ariaLabel="Sort by" />);
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Relevance' }));
    expect(screen.getByRole('button', { name: 'Date' })).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Date' })).not.toBeInTheDocument();
  });

  it('closes on outside click', async () => {
    render(
      <div>
        <button type="button">outside</button>
        <SelectMenu label="Sort by" value="relevance" options={options} onChange={vi.fn()} ariaLabel="Sort by" />
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Relevance' }));
    expect(screen.getByRole('button', { name: 'Date' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('button', { name: 'Date' })).not.toBeInTheDocument();
  });

  it('marks the active option pressed', async () => {
    render(<SelectMenu label="Sort by" value="date" options={options} onChange={vi.fn()} ariaLabel="Sort by" />);
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Date' }));
    expect(screen.getByRole('button', { name: 'Date' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Relevance' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders a bordered button trigger with the label+value and active styling', () => {
    render(
      <SelectMenu
        label="Show for"
        value="today"
        options={[
          { value: 'any', label: 'Any date' },
          { value: 'today', label: 'Today' },
        ]}
        onChange={vi.fn()}
        ariaLabel="Date"
        variant="button"
        active
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Show for Today' });
    expect(trigger).toBeInTheDocument();
    expect(trigger.className).toMatch(/triggerButtonActive/);
  });
});
