import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react';
import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import type { ChipOption } from '../Chip';
import styles from './SelectField.module.css';

interface SelectFieldProps {
  id: string;
  value: string;
  options: ChipOption[];
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  disabled?: boolean;
  /** C1-migrated surfaces (wayfinder #209): squares the trigger, popover
   * and option list. Additive, defaults off. */
  sharp?: boolean;
}

const ChevronIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
);

interface ListboxProps {
  flatOptions: ChipOption[];
  value: string;
  onSelect: (v: string) => void;
  ariaLabel: string;
  popRef: RefObject<HTMLDivElement>;
  sharp: boolean;
}

/** The open panel's option list — a separate component so its roving-tabindex
 * state is fresh on every open (mirrors DatePicker's PopoverBody). Implements
 * the ARIA listbox keyboard pattern (Arrow/Home/End move focus, Enter/Space
 * activate) since the panel carries role="listbox"/"option". */
function Listbox({ flatOptions, value, onSelect, ariaLabel, popRef, sharp }: ListboxProps) {
  const selectedIndex = Math.max(0, flatOptions.findIndex((o) => o.value === value));
  const [focusedIndex, setFocusedIndex] = useState(selectedIndex);
  const listRef = useRef<HTMLDivElement>(null);

  function focusIndex(index: number) {
    setFocusedIndex(index);
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]')[index]?.focus();
  }

  function handleKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        focusIndex(Math.min(focusedIndex + 1, flatOptions.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        focusIndex(Math.max(focusedIndex - 1, 0));
        break;
      case 'Home':
        e.preventDefault();
        focusIndex(0);
        break;
      case 'End':
        e.preventDefault();
        focusIndex(flatOptions.length - 1);
        break;
      default:
        break;
    }
  }

  return (
    <div className={cx(styles.pop, sharp && styles.sharp)} ref={popRef} role="listbox" aria-label={ariaLabel} onKeyDown={handleKeyDown}>
      <div ref={listRef}>
        {flatOptions.map((option, index) => {
          const isSelected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="option"
              tabIndex={index === focusedIndex ? 0 : -1}
              aria-selected={isSelected}
              data-selected={isSelected || undefined}
              className={cx(styles.option, isSelected && styles.optionSelected, option.value === '' && styles.placeholderOption, sharp && styles.sharp)}
              onFocus={() => setFocusedIndex(index)}
              onClick={() => onSelect(option.value)}
            >
              <span className={styles.optionGutter}>{isSelected && <span className={styles.blip} aria-hidden />}</span>
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Form-field-shaped single-select popover — themed replacement for a native
 * `<select>`. Used by EventSubmit's Category field; a field-width dark panel
 * distinct from SelectMenu's centered Explore-filter list. */
export default function SelectField({ id, value, options, onChange, placeholder, ariaLabel, disabled = false, sharp = false }: SelectFieldProps) {
  const { open, setOpen, rootRef, popRef, triggerRef, close } = useDropdown('[data-selected="true"]');
  const current = options.find((o) => o.value === value);
  const flatOptions: ChipOption[] = [{ value: '', label: placeholder }, ...options];

  function handleSelect(next: string) {
    onChange(next);
    close();
  }

  return (
    <div className={styles.selectField} ref={rootRef}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className={cx(styles.trigger, open && styles.triggerOpen, sharp && styles.sharp)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={current ? styles.value : styles.placeholder}>
          {current?.label ?? placeholder}
        </span>
        <span className={cx(styles.chev, open && styles.chevOpen)} aria-hidden>
          <ChevronIcon />
        </span>
      </button>
      {open && !disabled && (
        <Listbox flatOptions={flatOptions} value={value} onSelect={handleSelect} ariaLabel={ariaLabel} popRef={popRef} sharp={sharp} />
      )}
    </div>
  );
}
