import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SelectField from './SelectField';

const options = [
  { value: 'music', label: 'Music' },
  { value: 'art', label: 'Art' },
  { value: 'sports', label: 'Sports' },
];

describe('SelectField', () => {
  it('shows the placeholder when no value is selected', () => {
    render(<SelectField id="category" value="" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />);
    expect(screen.getByRole('button', { name: 'Category' })).toHaveTextContent('No category');
  });

  it('shows the current option label on the trigger', () => {
    render(<SelectField id="category" value="art" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />);
    expect(screen.getByRole('button', { name: 'Category' })).toHaveTextContent('Art');
  });

  it('opens the panel on trigger click', async () => {
    render(<SelectField id="category" value="" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />);
    expect(screen.queryByRole('option', { name: 'Music' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    expect(screen.getByRole('option', { name: 'Music' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Art' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Sports' })).toBeInTheDocument();
  });

  it('fires onChange and closes when an option is clicked', async () => {
    const onChange = vi.fn();
    render(<SelectField id="category" value="" options={options} onChange={onChange} placeholder="No category" ariaLabel="Category" />);
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    await userEvent.click(screen.getByRole('option', { name: 'Art' }));
    expect(onChange).toHaveBeenCalledWith('art');
    expect(screen.queryByRole('option', { name: 'Sports' })).not.toBeInTheDocument();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    render(<SelectField id="category" value="" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />);
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    expect(screen.getByRole('option', { name: 'Music' })).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('option', { name: 'Music' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Category' })).toHaveFocus();
  });

  it('closes on outside click', async () => {
    render(
      <div>
        <button type="button">outside</button>
        <SelectField id="category" value="" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    expect(screen.getByRole('option', { name: 'Music' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('option', { name: 'Music' })).not.toBeInTheDocument();
  });

  it('does not open when disabled', async () => {
    render(<SelectField id="category" value="" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" disabled />);
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    expect(screen.queryByRole('option', { name: 'Music' })).not.toBeInTheDocument();
  });

  it('marks the selected option aria-selected', async () => {
    render(<SelectField id="category" value="sports" options={options} onChange={vi.fn()} placeholder="No category" ariaLabel="Category" />);
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    expect(screen.getByRole('option', { name: 'Sports' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('option', { name: 'Music' })).toHaveAttribute('aria-selected', 'false');
  });

  it('clears the value when the placeholder option is clicked', async () => {
    const onChange = vi.fn();
    render(<SelectField id="category" value="sports" options={options} onChange={onChange} placeholder="No category" ariaLabel="Category" />);
    await userEvent.click(screen.getByRole('button', { name: 'Category' }));
    await userEvent.click(screen.getByRole('option', { name: 'No category' }));
    expect(onChange).toHaveBeenCalledWith('');
  });
});
