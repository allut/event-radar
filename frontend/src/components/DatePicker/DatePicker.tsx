import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react';
import {
  cx, monthGridDays, weekdayHeaders, splitDateTimeValue, joinDateTimeValue,
  formatPickerValue, formatMonthYearLabel, parseTypedDate, toDisplayDateTime, fromDisplayDateTime,
  clamp, tallinnToday, toDateStr, isSameDay, addDays, addMonths, padIndex, weekdayOffset,
} from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import {
  CALENDAR_WEEK_START,
  CALENDAR_DAYS_PER_WEEK,
  HOURS_PER_DAY,
  MINUTES_PER_HOUR,
  MIN_HOUR,
  MAX_HOUR,
  MIN_MINUTE,
  MAX_MINUTE,
  TIME_STEP_HOURS,
  TIME_STEP_MINUTES,
  TIME_FIELD_MAX_LENGTH,
  PICKER_VALUE_PLACEHOLDER,
  PICKER_DATE_ONLY_PLACEHOLDER,
  PICKER_MIDNIGHT_SUFFIX,
  PICKER_SKIP_LIMIT,
} from '../../constants/core';
import { t, ti } from '../../i18n';
import { PrevIcon, NextIcon } from '../ChevronIcons';
import styles from './DatePicker.module.css';

interface DatePickerProps {
  id: string;
  /** 'YYYY-MM-DDTHH:mm', same wire format as the native datetime-local input this replaces. */
  value: string;
  onChange: (value: string) => void;
  locale: string;
  disabled?: boolean;
  required?: boolean;
  /** Earlier days (in the same wire format) are greyed out and unselectable — Ends passes Starts. */
  min?: string;
  ariaLabel: string;
  /** Later days are greyed out and unselectable. Same format as `value`. */
  max?: string;
  /** Whole-day mode: `value`/`onChange`/`min`/`max` are 'YYYY-MM-DD', the time fields are hidden and the popover closes on a day pick. */
  dateOnly?: boolean;
  /** Days (as 'YYYY-MM-DD') greyed out and unselectable, by calendar or typed entry. */
  isDayDisabled?: (isoDate: string) => boolean;
  /** Marks the text field aria-invalid. */
  invalid?: boolean;
}

/** Widens a date-only value to the date-time wire format the parser reads. */
function widenValue(v: string, dateOnly: boolean): string {
  return dateOnly && v ? `${v}${PICKER_MIDNIGHT_SUFFIX}` : v;
}

/** Reads the hour/minute text fields back as bounded numbers — empty or
 * non-numeric text falls back to the field's minimum, matching what the field
 * displays once it re-pads on blur. */
function parseHourText(text: string): number {
  const n = Number(text);
  return clamp(Number.isNaN(n) ? MIN_HOUR : n, MIN_HOUR, MAX_HOUR);
}

function parseMinuteText(text: string): number {
  const n = Number(text);
  return clamp(Number.isNaN(n) ? MIN_MINUTE : n, MIN_MINUTE, MAX_MINUTE);
}

const CalendarIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
    <circle cx="7.5" cy="14" r="1" fill="currentColor" stroke="none" />
  </svg>
);

interface PopoverBodyProps {
  id: string;
  value: string;
  onChange: (v: string) => void;
  min?: string;
  max?: string;
  dateOnly: boolean;
  isDayDisabled?: (isoDate: string) => boolean;
  locale: string;
  required: boolean;
  disabled: boolean;
  popRef: RefObject<HTMLDivElement>;
  flip: boolean;
}

function PopoverBody({ id, value, onChange, min, max, dateOnly, isDayDisabled, locale, required, disabled, popRef, flip }: PopoverBodyProps) {
  const today = tallinnToday();
  const parsed = splitDateTimeValue(widenValue(value, dateOnly));
  const minParsed = min ? splitDateTimeValue(widenValue(min, dateOnly)) : null;
  const maxParsed = max ? splitDateTimeValue(widenValue(max, dateOnly)) : null;
  const maxDay = maxParsed ? new Date(maxParsed.year, maxParsed.month, maxParsed.day) : null;
  const isBlocked = (date: Date) =>
    Boolean((minDay && date < minDay) || (maxDay && date > maxDay) || isDayDisabled?.(toDateStr(date)));
  // First selectable day at or after `from`, walking by `step` days; `from`
  // itself when none is found within a year.
  function nextOpen(from: Date, step: number): Date {
    let d = from;
    for (let i = 0; i < PICKER_SKIP_LIMIT && isBlocked(d); i += 1) d = addDays(d, step);
    return isBlocked(d) ? from : d;
  }
  const minDay = minParsed ? new Date(minParsed.year, minParsed.month, minParsed.day) : null;
  // Full minute-resolution bound (not just the day) — a day-only comparison would
  // let the same calendar day as `min` commit with an earlier time (e.g. Ends
  // same day as Starts but before it), silently producing a negative-duration
  // event since neither this form nor the backend cross-validates starts/ends.
  const minDateTime = minParsed ? new Date(minParsed.year, minParsed.month, minParsed.day, minParsed.hour, minParsed.minute) : null;
  // With no value yet and a future min (Ends opened before Starts has been
  // picked), default the view to min's month rather than today's — today's
  // month would otherwise open with every cell disabled.
  const baseDay = parsed ? new Date(parsed.year, parsed.month, parsed.day) : (minDay && minDay > today ? minDay : today);
  const initialDay = !parsed && (maxDay || isDayDisabled) ? nextOpen(baseDay, 1) : baseDay;

  // Fresh state per mount — PopoverBody only exists while the popover is open
  // (DatePicker conditionally renders it), so every open re-derives from the
  // current `value`/`min` props instead of carrying stale state forward.
  const [viewYear, setViewYear] = useState(initialDay.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialDay.getMonth());
  const [focusedDay, setFocusedDay] = useState(initialDay);
  const [hourText, setHourText] = useState(padIndex(parsed ? parsed.hour : MIN_HOUR));
  const [minuteText, setMinuteText] = useState(padIndex(parsed ? parsed.minute : MIN_MINUTE));

  const gridRef = useRef<HTMLDivElement>(null);
  const focusPendingRef = useRef(false);

  const focusedDayKey = focusedDay.toDateString();

  useEffect(() => {
    if (!focusPendingRef.current || !gridRef.current) return;
    focusPendingRef.current = false;
    gridRef.current.querySelector<HTMLButtonElement>(`[data-date="${focusedDayKey}"]`)?.focus();
  }, [focusedDayKey]);

  const selectedDay = parsed ? new Date(parsed.year, parsed.month, parsed.day) : null;

  // Snaps (h, m) up to `minDateTime`'s time-of-day when `date` is the same
  // calendar day as the minimum — keeps the day selectable (only a wholly
  // earlier day is disabled) while still guaranteeing the committed value
  // never lands before `min` to the minute.
  function clampToMin(date: Date, h: number, m: number): [number, number] {
    if (!minDateTime || !isSameDay(date, minDateTime)) return [h, m];
    const candidate = new Date(date.getFullYear(), date.getMonth(), date.getDate(), h, m);
    if (candidate >= minDateTime) return [h, m];
    return [minDateTime.getHours(), minDateTime.getMinutes()];
  }

  function commitDay(date: Date) {
    if (disabled || isBlocked(date)) return;
    if (dateOnly) {
      onChange(toDateStr(date));
      return;
    }
    const [h, m] = clampToMin(date, parseHourText(hourText), parseMinuteText(minuteText));
    setHourText(padIndex(h));
    setMinuteText(padIndex(m));
    onChange(joinDateTimeValue(date, h, m));
  }

  function commitTime(h: number, m: number) {
    const base = selectedDay ?? focusedDay;
    if (disabled || isBlocked(base)) return;
    const [ch, cm] = clampToMin(base, h, m);
    if (ch !== h || cm !== m) {
      setHourText(padIndex(ch));
      setMinuteText(padIndex(cm));
    }
    onChange(joinDateTimeValue(base, ch, cm));
  }

  // Keystroke-time commit: skips values clampToMin would rewrite, so a value
  // mid-typed below min (e.g. Ends' hour on the same day as Starts) stays on
  // screen instead of being silently snapped back on every keystroke — that
  // snap made the field un-typeable, since each new digit landed on top of
  // the just-reverted one. Blur (commitTime above) still clamps, so an
  // invalid value never lands on the committed value. Defers to commitTime
  // for the actual base/clamp logic so the two can't drift apart.
  function commitTimeIfValid(h: number, m: number) {
    const base = selectedDay ?? focusedDay;
    const [ch, cm] = clampToMin(base, h, m);
    if (ch !== h || cm !== m) return;
    commitTime(h, m);
  }

  function moveFocus(next: Date) {
    focusPendingRef.current = true;
    setFocusedDay(next);
    if (next.getFullYear() !== viewYear || next.getMonth() !== viewMonth) {
      setViewYear(next.getFullYear());
      setViewMonth(next.getMonth());
    }
  }

  // Clamps focusedDay into the new month too (not just viewYear/viewMonth) —
  // otherwise no rendered cell matches focusedDay after nav, every cell's
  // tabIndex falls to -1, and the grid becomes unreachable via Tab. Uses
  // addMonths (not moveFocus) so it doesn't also steal DOM focus away from
  // the nav button that was just clicked.
  function goToMonth(delta: number) {
    const next = addMonths(focusedDay, delta);
    // Land on a selectable day of the new month when the clamped one is blocked.
    const landed = isBlocked(next) ? nextOpen(next, 1) : next;
    const target = landed.getMonth() === next.getMonth() ? landed : next;
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
    setFocusedDay(target);
  }

  function handleGridKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    const d = focusedDay;
    let next: Date | null = null;
    // Walk further in the key's direction past blocked days; stay put if none.
    const skip = (to: Date, step: number): Date => {
      const open = nextOpen(to, step);
      return isBlocked(open) ? d : open;
    };
    switch (e.key) {
      case 'ArrowLeft': next = skip(addDays(d, -1), -1); break;
      case 'ArrowRight': next = skip(addDays(d, 1), 1); break;
      case 'ArrowUp': next = skip(addDays(d, -CALENDAR_DAYS_PER_WEEK), -CALENDAR_DAYS_PER_WEEK); break;
      case 'ArrowDown': next = skip(addDays(d, CALENDAR_DAYS_PER_WEEK), CALENDAR_DAYS_PER_WEEK); break;
      case 'PageUp': next = skip(addMonths(d, -1), -1); break;
      case 'PageDown': next = skip(addMonths(d, 1), 1); break;
      case 'Home': next = skip(addDays(d, -weekdayOffset(d, CALENDAR_WEEK_START)), 1); break;
      case 'End': next = skip(addDays(d, CALENDAR_DAYS_PER_WEEK - 1 - weekdayOffset(d, CALENDAR_WEEK_START)), -1); break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        commitDay(d);
        return;
      default:
        return;
    }
    e.preventDefault();
    if (next) moveFocus(next);
  }

  function handleTimeKeyDown(e: ReactKeyboardEvent<HTMLInputElement>, unit: 'hour' | 'minute') {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    const delta = e.key === 'ArrowUp' ? 1 : -1;
    const h = parseHourText(hourText);
    const m = parseMinuteText(minuteText);
    if (unit === 'hour') {
      const next = (h + delta * TIME_STEP_HOURS + HOURS_PER_DAY) % HOURS_PER_DAY;
      setHourText(padIndex(next));
      commitTime(next, m);
    } else {
      const next = (m + delta * TIME_STEP_MINUTES + MINUTES_PER_HOUR) % MINUTES_PER_HOUR;
      setMinuteText(padIndex(next));
      commitTime(h, next);
    }
  }

  // Re-runs only when the visible month changes, not on every hour/minute
  // keystroke (each ~250 Date operations, incl. toDateString() per cell).
  const cells = useMemo(
    () => monthGridDays(viewYear, viewMonth, CALENDAR_WEEK_START),
    [viewYear, viewMonth],
  );
  // Re-runs only on locale change, not every hour/minute keystroke (7
  // Intl.format + 7 Date allocations) — same rationale as `cells` above.
  const headers = useMemo(() => weekdayHeaders(locale), [locale]);
  const monthYearLabel = useMemo(
    () => formatMonthYearLabel(viewYear, viewMonth, locale),
    [viewYear, viewMonth, locale],
  );

  const monthLabelId = `${id}-picker-month-label`;

  return (
    <div className={styles.pop} ref={popRef} data-flip={flip || undefined} role="dialog" aria-labelledby={monthLabelId}>
      <div className={styles.calHead}>
        <button type="button" className={styles.calNavBtn} aria-label={t('picker_prev_month', locale)} onClick={() => goToMonth(-1)}>
          <PrevIcon />
        </button>
        <span className={styles.calMonthLabel} id={monthLabelId}>{monthYearLabel}</span>
        <button type="button" className={styles.calNavBtn} aria-label={t('picker_next_month', locale)} onClick={() => goToMonth(1)}>
          <NextIcon />
        </button>
      </div>
      <span className={styles.srOnly} aria-live="polite">
        {ti('picker_month_year_label', locale, { value: monthYearLabel })}
      </span>
      <div className={styles.calWeekdays}>
        {headers.map((h) => <span key={h}>{h}</span>)}
      </div>
      <div className={styles.calGrid} role="grid" ref={gridRef} onKeyDown={handleGridKeyDown}>
        {cells.map((c) => {
          const isToday = isSameDay(c.date, today);
          const isSelected = selectedDay ? isSameDay(c.date, selectedDay) : false;
          const isFocused = isSameDay(c.date, focusedDay);
          const isBlockedDay = isBlocked(c.date);
          const isDisabled = disabled || isBlockedDay;
          return (
            <button
              key={c.key}
              type="button"
              role="gridcell"
              aria-selected={isSelected}
              tabIndex={isFocused ? 0 : -1}
              data-date={c.dataDate}
              data-selected-day={isFocused || undefined}
              disabled={isDisabled}
              aria-disabled={isBlockedDay || undefined}
              className={cx(styles.calDay, c.spill && styles.spill, isToday && styles.today, isSelected && styles.selected)}
              onClick={() => commitDay(c.date)}
            >
              {c.day}
            </button>
          );
        })}
      </div>
      <div className={styles.footer}>
        {!dateOnly && <div className={styles.timeGroup}>
          <span className={styles.timeLabel}>{t('picker_time_label', locale)}</span>
          <div className={styles.timeRow}>
            <input
              type="text"
              inputMode="numeric"
              maxLength={TIME_FIELD_MAX_LENGTH}
              className={styles.timeInput}
              value={hourText}
              aria-label={t('picker_hour_label', locale)}
              disabled={disabled}
              onChange={(e) => {
                const next = e.target.value.replace(/\D/g, '').slice(0, TIME_FIELD_MAX_LENGTH);
                setHourText(next);
                commitTimeIfValid(parseHourText(next), parseMinuteText(minuteText));
              }}
              onKeyDown={(e) => handleTimeKeyDown(e, 'hour')}
              onBlur={() => {
                const h = parseHourText(hourText);
                setHourText(padIndex(h));
                commitTime(h, parseMinuteText(minuteText));
              }}
            />
            <span className={styles.timeSeparator} aria-hidden>:</span>
            <input
              type="text"
              inputMode="numeric"
              maxLength={TIME_FIELD_MAX_LENGTH}
              className={styles.timeInput}
              value={minuteText}
              aria-label={t('picker_minute_label', locale)}
              disabled={disabled}
              onChange={(e) => {
                const next = e.target.value.replace(/\D/g, '').slice(0, TIME_FIELD_MAX_LENGTH);
                setMinuteText(next);
                commitTimeIfValid(parseHourText(hourText), parseMinuteText(next));
              }}
              onKeyDown={(e) => handleTimeKeyDown(e, 'minute')}
              onBlur={() => {
                const m = parseMinuteText(minuteText);
                setMinuteText(padIndex(m));
                commitTime(parseHourText(hourText), m);
              }}
            />
          </div>
        </div>}
        <div className={styles.footerActions}>
          <button type="button" className={styles.todayBtn} disabled={isBlocked(today)} onClick={() => { moveFocus(today); commitDay(today); }}>
            {t('picker_today', locale)}
          </button>
          {!required && value && (
            <button type="button" className={styles.clearBtn} onClick={() => onChange('')}>
              {t('picker_clear', locale)}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Shared date + time picker: a typeable text field plus a calendar-glyph button
 * opening a custom instrument-panel popover. Used by EventSubmit for both Starts
 * and Ends. The committed `value`/`onChange` contract is the same 'YYYY-MM-DDTHH:mm'
 * wire format as the native datetime-local input this replaces; the field displays
 * (and accepts typed input as) a space in place of the 'T' — see toDisplayDateTime. */
export default function DatePicker({ id, value, onChange, locale, disabled = false, required = false, min, max, dateOnly = false, isDayDisabled, invalid = false, ariaLabel }: DatePickerProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef } = useDropdown('[data-selected-day="true"]');
  // Holds the *displayed* text (space-separated — see toDisplayDateTime), not
  // the canonical 'T'-joined wire value.
  const [typedValue, setTypedValue] = useState(toDisplayDateTime(value));
  // Derived-state-during-render sync (React's documented pattern for this,
  // rather than a useEffect) — only fires when `value` changes from outside
  // (prefill, Clear, a day picked in the popover), never while the user is
  // actively typing, since typing alone doesn't change the `value` prop until blur.
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setTypedValue(toDisplayDateTime(value));
  }

  // Returns false when the text didn't parse, so the caller can decide whether
  // to leave it in place (still typing) or revert it (blurred with garbage).
  function commitTyped(text: string): boolean {
    if (text === '') {
      onChange('');
      return true;
    }
    if (dateOnly) {
      const day = parseTypedDate(widenValue(text, true)) === null ? null : text;
      if (day === null) return false;
      // Typed entry follows the calendar: an unselectable day is rejected, not snapped.
      if ((min && day < min) || (max && day > max) || isDayDisabled?.(day)) return false;
      onChange(day);
      return true;
    }
    const parsed = parseTypedDate(text);
    if (parsed === null) return false;
    if ((max && parsed > max) || isDayDisabled?.(parsed.slice(0, 10))) return false;
    // The wire format is a fixed-width zero-padded 'YYYY-MM-DDTHH:mm', so it
    // sorts chronologically as a plain string — no Date parsing needed here.
    // Mirrors PopoverBody's clampToMin: typed entry must not be able to commit
    // a value earlier than `min` when the calendar UI already prevents it.
    onChange(min && parsed < min ? min : parsed);
    return true;
  }

  const preview = dateOnly ? '' : formatPickerValue(value, locale);

  return (
    <div className={styles.datePicker} ref={rootRef}>
      <div className={cx(styles.field, disabled && styles.fieldDisabled)}>
        <input
          id={id}
          type="text"
          className={styles.textInput}
          value={typedValue}
          onChange={(e) => { setTypedValue(e.target.value); commitTyped(fromDisplayDateTime(e.target.value)); }}
          onBlur={(e) => { if (!commitTyped(fromDisplayDateTime(e.target.value))) setTypedValue(toDisplayDateTime(value)); }}
          aria-label={ariaLabel}
          placeholder={dateOnly ? PICKER_DATE_ONLY_PLACEHOLDER : PICKER_VALUE_PLACEHOLDER}
          aria-invalid={invalid || undefined}
          disabled={disabled}
          required={required}
        />
        <button
          ref={triggerRef}
          type="button"
          className={styles.calendarButton}
          aria-label={t('picker_open_calendar', locale)}
          aria-expanded={open}
          aria-haspopup="dialog"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
        >
          <CalendarIcon />
        </button>
      </div>
      {preview && <span className={styles.preview}>{preview}</span>}
      {open && !disabled && (
        <PopoverBody
          id={id}
          value={value}
          onChange={(v) => { onChange(v); if (v === '' || dateOnly) setOpen(false); }}
          min={min}
          max={max}
          dateOnly={dateOnly}
          isDayDisabled={isDayDisabled}
          locale={locale}
          required={required}
          disabled={disabled}
          popRef={popRef}
          flip={flip}
        />
      )}
    </div>
  );
}
