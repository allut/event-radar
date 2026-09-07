import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import type { ChipOption } from '../Chip';
import menuStyles from '../shared/Menu.module.css';
import styles from './SelectMenu.module.css';

interface SelectMenuProps {
  label: string;
  value: string;
  options: ChipOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  /** 'inline' blends into a cluster (e.g. next to a SegmentedControl); 'button'
   * is a bordered pill matching FacetMenu's trigger. Defaults to 'inline'. */
  variant?: 'inline' | 'button';
  /** 'button' variant only — highlights the trigger when a non-default value is selected. */
  active?: boolean;
  disabled?: boolean;
  /** Opens the popover above the trigger instead of below — for a trigger
   * pinned near the viewport bottom (AdminShell's foot area) where a
   * downward popover would overflow/clip. */
  openUpward?: boolean;
}

/** Single-select trigger + popover of a vertical, equal-width option list.
 * Used for Explore's Sort-by (inline) and Date (button) controls. */
export default function SelectMenu({
  label,
  value,
  options,
  onChange,
  ariaLabel,
  variant = 'inline',
  active = false,
  disabled = false,
  openUpward = false,
}: SelectMenuProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef, close } = useDropdown();
  const current = options.find((o) => o.value === value);

  function handleSelect(next: string) {
    onChange(next);
    close();
  }

  return (
    <div className={cx(menuStyles.menu, styles.selectMenu)} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={
          variant === 'button'
            ? cx(menuStyles.triggerButton, active && menuStyles.triggerButtonActive)
            : styles.triggerInline
        }
        aria-expanded={open}
        aria-haspopup="true"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.label}>{label}</span>{' '}
        <span className={styles.value}>{current?.label ?? value}</span>
        <span className={styles.chev} aria-hidden>▾</span>
      </button>
      {open && !disabled && (
        <div
          className={styles.pop}
          ref={popRef}
          data-flip={flip || undefined}
          data-open-upward={openUpward || undefined}
        >
          <div className={styles.optionList} role="group" aria-label={ariaLabel}>
            {options.map((option) => {
              const isActive = option.value === value;
              return (
                <button
                  key={option.value}
                  type="button"
                  className={cx(styles.option, isActive && styles.optionActive)}
                  onClick={() => handleSelect(option.value)}
                  aria-pressed={isActive}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
