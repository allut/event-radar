import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react';
import {
  cx, monthGridDays, weekdayHeaders, splitDateTimeValue, joinDateTimeValue,
  formatPickerValue, formatMonthYearLabel, parseTypedDate, toDisplayDateTime, fromDisplayDateTime,
} from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { CALENDAR_WEEK_START, CALENDAR_DAYS_PER_WEEK, TIME_STEP_MINUTES } from '../../constants';
import { t, ti } from '../../i18n';
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
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function addMonths(d: Date, n: number): Date {
  const r = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const daysInTarget = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate();
  r.setDate(Math.min(d.getDate(), daysInTarget));
  return r;
}

const PrevIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M15 6l-6 6 6 6" /></svg>
);
const NextIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M9 6l6 6-6 6" /></svg>
);
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
  locale: string;
  required: boolean;
  disabled: boolean;
  popRef: RefObject<HTMLDivElement>;
  flip: boolean;
}

function PopoverBody({ id, value, onChange, min, locale, required, disabled, popRef, flip }: PopoverBodyProps) {
  const today = startOfDay(new Date());
  const parsed = splitDateTimeValue(value);
  const minParsed = min ? splitDateTimeValue(min) : null;
  const minDay = minParsed ? new Date(minParsed.year, minParsed.month, minParsed.day) : null;
  // Full minute-resolution bound (not just the day) — a day-only comparison would
  // let the same calendar day as `min` commit with an earlier time (e.g. Ends
  // same day as Starts but before it), silently producing a negative-duration
  // event since neither this form nor the backend cross-validates starts/ends.
  const minDateTime = minParsed ? new Date(minParsed.year, minParsed.month, minParsed.day, minParsed.hour, minParsed.minute) : null;
  // With no value yet and a future min (Ends opened before Starts has been
  // picked), default the view to min's month rather than today's — today's
  // month would otherwise open with every cell disabled.
  const initialDay = parsed ? new Date(parsed.year, parsed.month, parsed.day) : (minDay && minDay > today ? minDay : today);

  // Fresh state per mount — PopoverBody only exists while the popover is open
  // (DatePicker conditionally renders it), so every open re-derives from the
  // current `value`/`min` props instead of carrying stale state forward.
  const [viewYear, setViewYear] = useState(initialDay.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialDay.getMonth());
  const [focusedDay, setFocusedDay] = useState(initialDay);
  const [hourText, setHourText] = useState(parsed ? String(parsed.hour).padStart(2, '0') : '00');
  const [minuteText, setMinuteText] = useState(parsed ? String(parsed.minute).padStart(2, '0') : '00');

  const gridRef = useRef<HTMLDivElement>(null);
  const focusPendingRef = useRef(false);

  useEffect(() => {
    if (!focusPendingRef.current || !gridRef.current) return;
    focusPendingRef.current = false;
    gridRef.current.querySelector<HTMLButtonElement>(`[data-date="${focusedDay.toDateString()}"]`)?.focus();
  }, [focusedDay]);

  const selectedDay = parsed ? new Date(parsed.year, parsed.month, parsed.day) : null;

  // Snaps (h, m) up to `minDateTime`'s time-of-day when `date` is the same
  // calendar day as the minimum — keeps the day selectable (only a wholly
  // earlier day is disabled) while still guaranteeing the committed value
  // never lands before `min` to the minute.
  function clampToMin(date: Date, h: number, m: number): [number, number] {
    if (!minDateTime || !sameDay(date, minDateTime)) return [h, m];
    const candidate = new Date(date.getFullYear(), date.getMonth(), date.getDate(), h, m);
    if (candidate >= minDateTime) return [h, m];
    return [minDateTime.getHours(), minDateTime.getMinutes()];
  }

  function commitDay(date: Date) {
    if (disabled || (minDay && date < minDay)) return;
    const [h, m] = clampToMin(date, clamp(Number(hourText) || 0, 0, 23), clamp(Number(minuteText) || 0, 0, 59));
    setHourText(String(h).padStart(2, '0'));
    setMinuteText(String(m).padStart(2, '0'));
    onChange(joinDateTimeValue(date, h, m));
  }

  function commitTime(h: number, m: number) {
    const base = selectedDay ?? focusedDay;
    if (disabled || (minDay && base < minDay)) return;
    const [ch, cm] = clampToMin(base, h, m);
    if (ch !== h || cm !== m) {
      setHourText(String(ch).padStart(2, '0'));
      setMinuteText(String(cm).padStart(2, '0'));
    }
    onChange(joinDateTimeValue(base, ch, cm));
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
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
    setFocusedDay(next);
  }

  function handleGridKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    const d = focusedDay;
    let next: Date | null = null;
    switch (e.key) {
      case 'ArrowLeft': next = addDays(d, -1); break;
      case 'ArrowRight': next = addDays(d, 1); break;
      case 'ArrowUp': next = addDays(d, -CALENDAR_DAYS_PER_WEEK); break;
      case 'ArrowDown': next = addDays(d, CALENDAR_DAYS_PER_WEEK); break;
      case 'PageUp': next = addMonths(d, -1); break;
      case 'PageDown': next = addMonths(d, 1); break;
      case 'Home': next = addDays(d, -((d.getDay() - CALENDAR_WEEK_START + 7) % 7)); break;
      case 'End': next = addDays(d, 6 - ((d.getDay() - CALENDAR_WEEK_START + 7) % 7)); break;
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
    const h = clamp(Number(hourText) || 0, 0, 23);
    const m = clamp(Number(minuteText) || 0, 0, 59);
    if (unit === 'hour') {
      const next = (h + delta + 24) % 24;
      setHourText(String(next).padStart(2, '0'));
      commitTime(next, m);
    } else {
      const next = (m + delta * TIME_STEP_MINUTES + 60) % 60;
      setMinuteText(String(next).padStart(2, '0'));
      commitTime(h, next);
    }
  }

  const cells = monthGridDays(viewYear, viewMonth, CALENDAR_WEEK_START);
  const headers = weekdayHeaders(locale);
  const monthYearLabel = formatMonthYearLabel(viewYear, viewMonth, locale);

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
          const isToday = sameDay(c.date, today);
          const isSelected = selectedDay ? sameDay(c.date, selectedDay) : false;
          const isFocused = sameDay(c.date, focusedDay);
          const isDisabled = disabled || Boolean(minDay && c.date < minDay);
          return (
            <button
              key={c.date.toISOString()}
              type="button"
              role="gridcell"
              aria-selected={isSelected}
              tabIndex={isFocused ? 0 : -1}
              data-date={c.date.toDateString()}
              data-selected-day={isFocused || undefined}
              disabled={isDisabled}
              className={cx(styles.calDay, c.spill && styles.spill, isToday && styles.today, isSelected && styles.selected)}
              onClick={() => commitDay(c.date)}
            >
              {c.day}
            </button>
          );
        })}
      </div>
      <div className={styles.footer}>
        <div className={styles.timeGroup}>
          <span className={styles.timeLabel}>{t('picker_time_label', locale)}</span>
          <div className={styles.timeRow}>
            <input
              type="text"
              inputMode="numeric"
              maxLength={2}
              className={styles.timeInput}
              value={hourText}
              aria-label={t('picker_hour_label', locale)}
              disabled={disabled}
              onChange={(e) => {
                const next = e.target.value.replace(/\D/g, '').slice(0, 2);
                setHourText(next);
                commitTime(clamp(Number(next) || 0, 0, 23), clamp(Number(minuteText) || 0, 0, 59));
              }}
              onKeyDown={(e) => handleTimeKeyDown(e, 'hour')}
              onBlur={() => {
                const h = clamp(Number(hourText) || 0, 0, 23);
                setHourText(String(h).padStart(2, '0'));
                commitTime(h, clamp(Number(minuteText) || 0, 0, 59));
              }}
            />
            <span className={styles.timeSeparator} aria-hidden>:</span>
            <input
              type="text"
              inputMode="numeric"
              maxLength={2}
              className={styles.timeInput}
              value={minuteText}
              aria-label={t('picker_minute_label', locale)}
              disabled={disabled}
              onChange={(e) => {
                const next = e.target.value.replace(/\D/g, '').slice(0, 2);
                setMinuteText(next);
                commitTime(clamp(Number(hourText) || 0, 0, 23), clamp(Number(next) || 0, 0, 59));
              }}
              onKeyDown={(e) => handleTimeKeyDown(e, 'minute')}
              onBlur={() => {
                const m = clamp(Number(minuteText) || 0, 0, 59);
                setMinuteText(String(m).padStart(2, '0'));
                commitTime(clamp(Number(hourText) || 0, 0, 23), m);
              }}
            />
          </div>
        </div>
        <div className={styles.footerActions}>
          <button type="button" className={styles.todayBtn} onClick={() => { moveFocus(today); commitDay(today); }}>
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
export default function DatePicker({ id, value, onChange, locale, disabled = false, required = false, min, ariaLabel }: DatePickerProps) {
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
    const parsed = parseTypedDate(text);
    if (parsed === null) return false;
    // The wire format is a fixed-width zero-padded 'YYYY-MM-DDTHH:mm', so it
    // sorts chronologically as a plain string — no Date parsing needed here.
    // Mirrors PopoverBody's clampToMin: typed entry must not be able to commit
    // a value earlier than `min` when the calendar UI already prevents it.
    onChange(min && parsed < min ? min : parsed);
    return true;
  }

  const preview = formatPickerValue(value, locale);

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
          placeholder="YYYY-MM-DD HH:mm"
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
          onChange={(v) => { onChange(v); if (v === '') setOpen(false); }}
          min={min}
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
