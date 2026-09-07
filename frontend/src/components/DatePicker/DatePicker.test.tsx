import { useState } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DatePicker from './DatePicker';
import { renderWithProviders } from '../../test/utils';

function Harness({ initial = '', min, required = false, disabled = false }: { initial?: string; min?: string; required?: boolean; disabled?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <DatePicker
      id="starts_at"
      value={value}
      onChange={setValue}
      locale="en"
      min={min}
      required={required}
      disabled={disabled}
      ariaLabel="Starts"
    />
  );
}

describe('DatePicker', () => {
  it('renders a labeled, typeable text field and a calendar toggle button', () => {
    renderWithProviders(<Harness />);
    expect(screen.getByLabelText('Starts')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open calendar/i })).toBeInTheDocument();
  });

  it('opens the popover on calendar button click, showing the month header', async () => {
    renderWithProviders(<Harness initial="2026-08-01T18:00" />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));
    expect(await screen.findByRole('dialog')).toHaveTextContent('August 2026');
  });

  it('selects a day and displays it space-separated (committed value stays T-joined)', async () => {
    const { container } = renderWithProviders(<Harness initial="2026-08-01T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    const targetDate = new Date(2026, 7, 15);
    const cell = container.querySelector(`[data-date="${targetDate.toDateString()}"]`) as HTMLElement;
    expect(cell).toBeTruthy();
    await userEvent.click(cell);

    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 18:00');
  });

  it('respects min by disabling earlier days', async () => {
    const { container } = renderWithProviders(<Harness initial="2026-08-15T18:00" min="2026-08-10T00:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    const earlierDate = new Date(2026, 7, 5);
    const cell = container.querySelector(`[data-date="${earlierDate.toDateString()}"]`) as HTMLElement;
    expect(cell).toBeDisabled();
  });

  it('clamps a same-day time earlier than min up to the min time, instead of committing before it', async () => {
    // Pin "today" before min's month, so the empty-value popover opens on
    // min's month (its fallback view) rather than the real system clock's
    // current month, which drifts past the hardcoded min date over time.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 6, 1));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    const { container } = renderWithProviders(<Harness initial="" min="2026-08-15T20:00" />);
    await user.click(screen.getByRole('button', { name: /open calendar/i }));

    const sameDayAsMin = new Date(2026, 7, 15);
    const cell = container.querySelector(`[data-date="${sameDayAsMin.toDateString()}"]`) as HTMLElement;
    expect(cell).not.toBeDisabled();
    await user.click(cell);

    // Default time (00:00) is before min's 20:00 — must clamp up, never commit 00:00.
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 20:00');
    vi.useRealTimers();
  });

  it('allows free typing of an hour before validating against a same-day min, clamping only on blur', async () => {
    renderWithProviders(<Harness initial="2026-08-15T18:00" min="2026-08-15T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    const hourInput = screen.getByLabelText('Hour');
    await userEvent.clear(hourInput);
    await userEvent.type(hourInput, '14');
    // Mid-type, below min's hour — must not snap back and eat keystrokes.
    expect(hourInput).toHaveValue('14');
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 18:00');

    await userEvent.tab();
    expect(hourInput).toHaveValue('18');
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 18:00');
  });

  it('updates the trigger field live while typing the hour/minute, not only on blur', async () => {
    renderWithProviders(<Harness initial="2026-08-15T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    const hourInput = screen.getByLabelText('Hour');
    await userEvent.clear(hourInput);
    await userEvent.type(hourInput, '09');
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 09:00');

    const minuteInput = screen.getByLabelText('Minute');
    await userEvent.clear(minuteInput);
    await userEvent.type(minuteInput, '45');
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-15 09:45');
  });

  it('closes on Escape', async () => {
    renderWithProviders(<Harness initial="2026-08-01T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('navigates the grid with arrow keys and selects with Enter', async () => {
    const { container } = renderWithProviders(<Harness initial="2026-08-15T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    const startDate = new Date(2026, 7, 15);
    const startCell = container.querySelector(`[data-date="${startDate.toDateString()}"]`) as HTMLElement;
    expect(startCell).toHaveFocus();

    await userEvent.keyboard('{ArrowRight}');
    const nextDate = new Date(2026, 7, 16);
    const nextCell = container.querySelector(`[data-date="${nextDate.toDateString()}"]`) as HTMLElement;
    expect(nextCell).toHaveFocus();

    await userEvent.keyboard('{Enter}');
    expect(screen.getByLabelText('Starts')).toHaveValue('2026-08-16 18:00');
  });

  it('keeps a cell tabbable after navigating months with the nav buttons', async () => {
    const { container } = renderWithProviders(<Harness initial="2026-08-15T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));

    await userEvent.click(screen.getByRole('button', { name: /next month/i }));
    expect(await screen.findByRole('dialog')).toHaveTextContent('September 2026');

    const focusable = container.querySelector('[role="grid"] [tabindex="0"]');
    expect(focusable).not.toBeNull();
    expect(focusable).toHaveAttribute('data-selected-day', 'true');
  });

  it('typing a full value (space-separated, not T) commits it without requiring blur', async () => {
    renderWithProviders(<Harness />);
    const input = screen.getByLabelText('Starts');
    await userEvent.type(input, '2026-08-01 18:00');
    expect(input).toHaveValue('2026-08-01 18:00');
  });

  it('clamps a typed value earlier than min up to min, mirroring the calendar path', async () => {
    renderWithProviders(<Harness min="2026-08-15T20:00" />);
    const input = screen.getByLabelText('Starts');
    await userEvent.type(input, '2026-08-15 10:00');
    expect(input).toHaveValue('2026-08-15 20:00');
  });

  it('reverts an unparseable typed value back to the last committed value on blur', async () => {
    renderWithProviders(<Harness initial="2026-08-01T18:00" />);
    const input = screen.getByLabelText('Starts');
    // Append garbage rather than clearing first — clearing itself commits ''
    // (a valid empty value), which would make this test trivially pass.
    await userEvent.type(input, 'x');
    expect(input).toHaveValue('2026-08-01 18:00x');

    await userEvent.tab();
    await screen.findByDisplayValue('2026-08-01 18:00');
  });

  it('the placeholder and typed format use a space, not the raw T delimiter', () => {
    renderWithProviders(<Harness />);
    expect(screen.getByLabelText('Starts')).toHaveAttribute('placeholder', 'YYYY-MM-DD HH:mm');
  });

  it('disables the text input and calendar button when disabled', () => {
    renderWithProviders(<Harness disabled />);
    expect(screen.getByLabelText('Starts')).toBeDisabled();
    expect(screen.getByRole('button', { name: /open calendar/i })).toBeDisabled();
  });

  it('shows a Clear action for an optional field with a value, which empties it', async () => {
    renderWithProviders(<Harness initial="2026-08-01T18:00" />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));
    await userEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(screen.getByLabelText('Starts')).toHaveValue('');
  });

  it('does not show Clear for a required field', async () => {
    renderWithProviders(<Harness initial="2026-08-01T18:00" required />);
    await userEvent.click(screen.getByRole('button', { name: /open calendar/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /clear/i })).not.toBeInTheDocument();
  });

  it('calls onChange for a controlled empty value without crashing (Harness sanity)', () => {
    const onChange = vi.fn();
    renderWithProviders(<DatePicker id="x" value="" onChange={onChange} locale="en" ariaLabel="X" />);
    expect(screen.getByLabelText('X')).toHaveValue('');
  });
});
