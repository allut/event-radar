import { useState } from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DateRangeMenu from './DateRangeMenu';
import { renderWithProviders } from '../../test/utils';
import type { DatePreset } from '../../constants/explore';

function Harness({ initialPreset = 'any' as DatePreset, initialFrom = null as string | null, initialTo = null as string | null }) {
  const [value, setValue] = useState<DatePreset>(initialPreset);
  const [customFrom, setCustomFrom] = useState(initialFrom);
  const [customTo, setCustomTo] = useState(initialTo);
  return (
    <DateRangeMenu
      label="Show for"
      value={value}
      customFrom={customFrom}
      customTo={customTo}
      onSelectPreset={setValue}
      onChangeCustomRange={(from, to) => {
        setValue('custom');
        setCustomFrom(from);
        setCustomTo(to);
      }}
      locale="en"
      ariaLabel="Date"
    />
  );
}

function dataDate(y: number, m: number, d: number): string {
  return new Date(y, m, d).toDateString();
}

describe('DateRangeMenu', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the current preset on the trigger', () => {
    renderWithProviders(<Harness initialPreset="7d" />);
    expect(screen.getByRole('button', { name: 'Show for Next 7 days' })).toBeInTheDocument();
  });

  it('opens the popover with the preset list, preset selection still works', async () => {
    renderWithProviders(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Show for Any date' }));
    expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Today' }));
    expect(screen.getByRole('button', { name: 'Show for Today' })).toBeInTheDocument();
  });

  it('clicking "Custom range" opens calendar mode instead of selecting-and-closing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 10)); // 10 Sep 2026
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    renderWithProviders(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Show for Any date' }));
    await user.click(screen.getByRole('button', { name: 'Custom range' }));

    expect(screen.getByText('September 2026')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Today' })).not.toBeInTheDocument();
  });

  it('two clicks commit a range and close the popover', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 10));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    const { container } = renderWithProviders(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Show for Any date' }));
    await user.click(screen.getByRole('button', { name: 'Custom range' }));

    const from = container.querySelector(`[data-date="${dataDate(2026, 8, 12)}"]`) as HTMLElement;
    const to = container.querySelector(`[data-date="${dataDate(2026, 8, 20)}"]`) as HTMLElement;
    await user.click(from);
    await user.click(to);

    expect(screen.getByRole('button', { name: /^Show for 12 Sep\w* – 20 Sep\w*$/ })).toBeInTheDocument();
    expect(screen.queryByText('September 2026')).not.toBeInTheDocument();
  });

  it('clicking a day before the chosen "from" restarts the range', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 10));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    const { container } = renderWithProviders(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Show for Any date' }));
    await user.click(screen.getByRole('button', { name: 'Custom range' }));

    const later = container.querySelector(`[data-date="${dataDate(2026, 8, 20)}"]`) as HTMLElement;
    const earlier = container.querySelector(`[data-date="${dataDate(2026, 8, 12)}"]`) as HTMLElement;
    await user.click(later);
    await user.click(earlier);
    // Restarted: "earlier" is now pending "from", not yet committed — the
    // popover stays open in calendar mode instead of closing.
    expect(screen.getByText('September 2026')).toBeInTheDocument();

    const end = container.querySelector(`[data-date="${dataDate(2026, 8, 25)}"]`) as HTMLElement;
    await user.click(end);
    expect(screen.getByRole('button', { name: /^Show for 12 Sep\w* – 25 Sep\w*$/ })).toBeInTheDocument();
  });

  it('"prev month" is disabled at the current month', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 10));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    renderWithProviders(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Show for Any date' }));
    await user.click(screen.getByRole('button', { name: 'Custom range' }));

    expect(screen.getByRole('button', { name: 'Previous month' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next month' }));
    expect(screen.getByText('October 2026')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous month' })).not.toBeDisabled();
  });

  it('reopening an active custom range pre-seeds calendar mode with its month', async () => {
    renderWithProviders(<Harness initialPreset="custom" initialFrom="2026-09-01" initialTo="2026-09-15" />);
    const trigger = screen.getByRole('button', { name: /^Show for 1 Sep\w* – 15 Sep\w*$/ });
    expect(trigger).toBeInTheDocument();
    await userEvent.click(trigger);
    expect(screen.getByText('September 2026')).toBeInTheDocument();
  });

  it('the back button returns to the preset list without committing', async () => {
    renderWithProviders(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Show for Any date' }));
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    await userEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument();
  });
});
