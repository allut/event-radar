import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CategoryPicker from './CategoryPicker';

const options = [
  { value: 'music', label: 'Music' },
  { value: 'theater', label: 'Theatre' },
  { value: 'family', label: 'Family' },
];

function setup(props: Partial<React.ComponentProps<typeof CategoryPicker>> = {}) {
  const onToggle = vi.fn();
  render(
    <CategoryPicker
      options={options}
      selected={[]}
      max={2}
      onToggle={onToggle}
      ariaLabel="Categories"
      locale="en"
      {...props}
    />,
  );
  return onToggle;
}

describe('CategoryPicker', () => {
  it('shows the empty text when nothing is picked', () => {
    setup();
    expect(screen.getByText('None picked yet')).toBeInTheDocument();
  });

  it('lists unpicked options as buttons and toggles on click', async () => {
    const onToggle = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Theatre' }));
    expect(onToggle).toHaveBeenCalledWith('theater');
  });

  it('renders picked options as removable tags in pick order', async () => {
    const onToggle = setup({ selected: ['family', 'music'] });
    const tags = screen.getAllByRole('button', { name: /^Remove / });
    expect(tags.map((b) => b.getAttribute('aria-label'))).toEqual(['Remove Family', 'Remove Music']);
    await userEvent.click(screen.getByRole('button', { name: 'Remove Music' }));
    expect(onToggle).toHaveBeenCalledWith('music');
    expect(screen.queryByRole('button', { name: 'Music' })).not.toBeInTheDocument();
  });

  it('dims and ignores unpicked options at the cap, keeping them focusable', async () => {
    const onToggle = setup({ selected: ['music', 'family'] });
    const option = screen.getByRole('button', { name: 'Theatre' });
    expect(option).toHaveAttribute('aria-disabled', 'true');
    expect(option).not.toBeDisabled();
    await userEvent.click(option);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('renders locked options as read-only tags that still count toward the cap', () => {
    setup({ selected: ['music', 'family'], locked: ['music'] });
    expect(screen.queryByRole('button', { name: 'Remove Music' })).not.toBeInTheDocument();
    expect(screen.getByText(/Music/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove Family' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Theatre' })).toHaveAttribute('aria-disabled', 'true');
  });

  it('disables every control while disabled', () => {
    setup({ selected: ['music'], disabled: true });
    expect(screen.getByRole('button', { name: 'Remove Music' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Theatre' })).toBeDisabled();
  });
});
