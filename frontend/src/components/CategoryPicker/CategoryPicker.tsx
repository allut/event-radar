import { useMemo } from 'react';
import { t, ti } from '../../i18n';
import { cx } from '../../utils';
import type { ChipOption } from '../Chip';
import styles from './CategoryPicker.module.css';

interface CategoryPickerProps {
  options: ChipOption[];
  /** Picked values in pick order — `locked` ones included. */
  selected: string[];
  /** Picked values that can't be removed (claim edits never drop an existing
   * category); they render as read-only tags and count toward `max`. */
  locked?: string[];
  max: number;
  onToggle: (value: string) => void;
  ariaLabel: string;
  locale: string;
  disabled?: boolean;
}

/** Capped multi-select: picked options sit on top as removable tags, the rest
 * below as a quiet list. At the cap the unpicked options dim and ignore
 * clicks (aria-disabled, not disabled, so they stay focusable). */
export default function CategoryPicker({
  options, selected, locked = [], max, onToggle, ariaLabel, locale, disabled = false,
}: CategoryPickerProps) {
  const labels = useMemo(() => new Map(options.map((o) => [o.value, o.label])), [options]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const lockedSet = useMemo(() => new Set(locked), [locked]);
  const atCap = selected.length >= max;
  const rest = options.filter((o) => !selectedSet.has(o.value));

  return (
    <div className={styles.picker} role="group" aria-label={ariaLabel}>
      <div className={styles.picked}>
        {selected.length === 0 && (
          <span className={styles.empty}>{t('organizer_categories_none', locale)}</span>
        )}
        {selected.map((value) => {
          const label = labels.get(value) ?? value;
          if (lockedSet.has(value)) {
            return (
              <span key={value} className={cx(styles.tag, styles.tagLocked)}>✓ {label}</span>
            );
          }
          return (
            <button
              key={value}
              type="button"
              className={styles.tag}
              onClick={() => onToggle(value)}
              disabled={disabled}
              aria-label={ti('organizer_categories_remove', locale, { name: label })}
            >
              <span>{label}</span>
              <span className={styles.remove} aria-hidden="true">✕</span>
            </button>
          );
        })}
      </div>
      <div className={cx(styles.rest, atCap && styles.atCap)}>
        {rest.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            className={styles.option}
            onClick={() => { if (!atCap) onToggle(value); }}
            disabled={disabled}
            aria-disabled={atCap || undefined}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
