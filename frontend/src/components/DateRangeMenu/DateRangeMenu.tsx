import { memo, useMemo, useState } from 'react';
import {
  cx, monthGridDays, weekdayHeaders, formatMonthYearLabel, formatDateRangeShort, formatDateShort,
  parseISODateLocal, toDateStr, tallinnToday, isSameDay, addMonths,
} from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { CALENDAR_WEEK_START, DATE_PRESETS, type DatePreset } from '../../constants';
import { t } from '../../i18n';
import { PrevIcon, NextIcon } from '../ChevronIcons';
import styles from './DateRangeMenu.module.css';

interface DateRangeMenuProps {
  label: string;
  value: DatePreset;
  customFrom: string | null;
  customTo: string | null;
  onSelectPreset: (preset: DatePreset) => void;
  onChangeCustomRange: (from: string, to: string) => void;
  locale: string;
  ariaLabel: string;
}

interface CalendarBodyProps {
  customFrom: string | null;
  customTo: string | null;
  locale: string;
  onBack: () => void;
  onCommit: (from: string, to: string) => void;
}

/** Date-only range grid, modeled on DatePicker's PopoverBody minus the time
 * footer. Fresh state per mount — only rendered while calendar mode is
 * active, so re-entering it re-derives from the current customFrom/customTo. */
function CalendarBody({ customFrom, customTo, locale, onBack, onCommit }: CalendarBodyProps) {
  const today = tallinnToday();
  const committedFrom = customFrom ? parseISODateLocal(customFrom) : null;
  const committedTo = customTo ? parseISODateLocal(customTo) : null;
  const initialDay = committedFrom ?? today;

  const [viewYear, setViewYear] = useState(initialDay.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialDay.getMonth());
  const [pendingFrom, setPendingFrom] = useState<Date | null>(null);

  const displayFrom = pendingFrom ?? committedFrom;
  const displayTo = pendingFrom ? null : committedTo;

  function goToMonth(delta: number) {
    const next = addMonths(new Date(viewYear, viewMonth, 1), delta);
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
  }

  function handleDayClick(date: Date) {
    if (date < today) return;
    if (!pendingFrom) {
      setPendingFrom(date);
      return;
    }
    if (date < pendingFrom) {
      setPendingFrom(date);
      return;
    }
    onCommit(toDateStr(pendingFrom), toDateStr(date));
  }

  // Re-run only when the visible month/locale changes, not on every day
  // click (pendingFrom) — matches DatePicker's `cells` memoization.
  const cells = useMemo(
    () => monthGridDays(viewYear, viewMonth, CALENDAR_WEEK_START),
    [viewYear, viewMonth],
  );
  const headers = useMemo(() => weekdayHeaders(locale), [locale]);
  const monthYearLabel = useMemo(
    () => formatMonthYearLabel(viewYear, viewMonth, locale),
    [viewYear, viewMonth, locale],
  );
  const isCurrentMonth = viewYear === today.getFullYear() && viewMonth === today.getMonth();

  return (
    <>
      <button type="button" className={styles.back} onClick={onBack}>
        <PrevIcon /> {t('back', locale)}
      </button>
      <div className={styles.calHead}>
        <button
          type="button"
          className={styles.calNavBtn}
          aria-label={t('picker_prev_month', locale)}
          disabled={isCurrentMonth}
          onClick={() => goToMonth(-1)}
        >
          <PrevIcon />
        </button>
        <span className={styles.calMonthLabel}>{monthYearLabel}</span>
        <button type="button" className={styles.calNavBtn} aria-label={t('picker_next_month', locale)} onClick={() => goToMonth(1)}>
          <NextIcon />
        </button>
      </div>
      <div className={styles.rangeHint}>
        <span className={cx(styles.hintPart, !displayFrom && styles.hintPartActive)}>
          {displayFrom ? formatDateShort(displayFrom, locale) : t('date_from', locale)}
        </span>
        <span className={cx(styles.hintPart, Boolean(displayFrom) && !displayTo && styles.hintPartActive)}>
          {displayTo ? formatDateShort(displayTo, locale) : t('date_to', locale)}
        </span>
      </div>
      <div className={styles.calWeekdays}>
        {headers.map((h) => <span key={h}>{h}</span>)}
      </div>
      <div className={styles.calGrid}>
        {cells.map((c) => {
          const isToday = isSameDay(c.date, today);
          const isDisabled = c.date < today;
          const isStart = displayFrom ? isSameDay(c.date, displayFrom) : false;
          const isEnd = displayTo ? isSameDay(c.date, displayTo) : false;
          const isInRange = Boolean(displayFrom && displayTo && c.date > displayFrom && c.date < displayTo);
          return (
            <button
              key={c.key}
              type="button"
              disabled={isDisabled}
              data-date={c.dataDate}
              className={cx(
                styles.calDay,
                c.spill && styles.spill,
                isToday && styles.today,
                (isStart || isEnd) && styles.rangeEndpoint,
                isInRange && styles.inRange,
              )}
              onClick={() => handleDayClick(c.date)}
            >
              {c.day}
            </button>
          );
        })}
      </div>
    </>
  );
}

/** Explore's Date filter: same trigger-button + popover shape as SelectMenu,
 * but the 'custom' preset entry opens a calendar-grid range picker instead of
 * selecting-and-closing. Explore-date-specific, not a general-purpose list
 * picker — see SelectMenu for that. memo'd — see SegmentedControl's
 * docstring (Big-O audit #5, item 3.6). */
const DateRangeMenu = memo(function DateRangeMenu({
  label, value, customFrom, customTo, onSelectPreset, onChangeCustomRange, locale, ariaLabel,
}: DateRangeMenuProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef, close } = useDropdown();
  const [mode, setMode] = useState<'list' | 'calendar'>('list');

  const current = DATE_PRESETS.find((p) => p.value === value);
  const triggerLabel =
    value === 'custom' && customFrom && customTo
      ? formatDateRangeShort(customFrom, customTo, locale)
      : (current?.labelKey ? t(current.labelKey, locale) : value);

  function handleOpen() {
    setMode(value === 'custom' ? 'calendar' : 'list');
    setOpen((v) => !v);
  }

  function handleSelect(preset: DatePreset) {
    if (preset === 'custom') {
      setMode('calendar');
      return;
    }
    onSelectPreset(preset);
    close();
  }

  function handleCommit(from: string, to: string) {
    onChangeCustomRange(from, to);
    close();
  }

  return (
    <div className={styles.menu} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.triggerInline}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={handleOpen}
      >
        <span className={styles.label}>{label}</span>{' '}
        <span className={styles.value}>{triggerLabel}</span>
        <span className={styles.chev} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={cx(styles.pop, mode === 'calendar' && styles.popCalendar)} ref={popRef} data-flip={flip || undefined}>
          {mode === 'list' ? (
            <div className={styles.optionList} role="group" aria-label={ariaLabel}>
              {DATE_PRESETS.map((option) => {
                const isActive = option.value === value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={cx(styles.option, isActive && styles.optionActive)}
                    onClick={() => handleSelect(option.value)}
                    aria-pressed={isActive}
                  >
                    {t(option.labelKey, locale)}
                  </button>
                );
              })}
            </div>
          ) : (
            <CalendarBody
              customFrom={customFrom}
              customTo={customTo}
              locale={locale}
              onBack={() => setMode('list')}
              onCommit={handleCommit}
            />
          )}
        </div>
      )}
    </div>
  );
});

export default DateRangeMenu;
