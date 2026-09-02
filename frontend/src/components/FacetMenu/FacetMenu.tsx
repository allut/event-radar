import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { DROPDOWN_DEFAULT_FOCUS_SELECTOR } from '../../constants';
import Chip, { type ChipOption } from '../Chip';
import menuStyles from '../shared/Menu.module.css';
import styles from './FacetMenu.module.css';

interface FacetMenuProps {
  label: string;
  options: ChipOption[];
  selected: string[];
  onToggle: (value: string) => void;
  ariaLabel: string;
  /** 'button' is a bordered pill (default); 'inline' blends into a cluster
   * (e.g. next to another FacetMenu), matching SelectMenu's inline variant. */
  variant?: 'button' | 'inline';
  /** C1-migrated surfaces (wayfinder #200): squares the trigger, popover and
   * option pills. Additive, defaults off so unmigrated consumers are unaffected. */
  sharp?: boolean;
}

/** Trigger button + popover for one Explore facet (Category/Vibe/When).
 * Popover options reuse the shared Chip pill component. */
export default function FacetMenu({
  label,
  options,
  selected,
  onToggle,
  ariaLabel,
  variant = 'button',
  sharp = false,
}: FacetMenuProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef } = useDropdown(
    DROPDOWN_DEFAULT_FOCUS_SELECTOR,
    '--facet-pop-top',
  );
  const hasSelection = selected.length > 0;

  return (
    <div className={menuStyles.menu} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={cx(
          variant === 'inline'
            ? cx(styles.menuBtnInline, hasSelection && styles.hasInline)
            : cx(styles.menuBtn, hasSelection && styles.has),
          sharp && styles.sharp,
        )}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
      >
        {hasSelection ? `${label} · ${selected.length}` : label}
        <span className={styles.chev} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={cx(styles.pop, sharp && styles.sharp)} ref={popRef} data-flip={flip || undefined}>
          <Chip options={options} selected={selected} onToggle={onToggle} ariaLabel={ariaLabel} sharp={sharp} />
        </div>
      )}
    </div>
  );
}
