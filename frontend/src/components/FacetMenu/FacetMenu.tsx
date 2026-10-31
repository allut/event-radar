import { memo } from 'react';
import { cx } from '../../utils/style';
import { useDropdown } from '../../hooks/useDropdown';
import { DROPDOWN_DEFAULT_FOCUS_SELECTOR } from '../../constants/core';
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
}

/** Trigger button + popover for one Explore facet (Category/Vibe/When).
 * Popover options reuse the shared Chip pill component. memo'd — see
 * SegmentedControl's docstring (Big-O audit #5, item 3.6). */
const FacetMenu = memo(function FacetMenu({
  label,
  options,
  selected,
  onToggle,
  ariaLabel,
  variant = 'button',
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
        className={
          variant === 'inline'
            ? cx(styles.menuBtnInline, hasSelection && styles.hasInline)
            : cx(styles.menuBtn, hasSelection && styles.has)
        }
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
      >
        {hasSelection ? `${label} · ${selected.length}` : label}
        <span className={styles.chev} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={styles.pop} ref={popRef} data-flip={flip || undefined}>
          <Chip options={options} selected={selected} onToggle={onToggle} ariaLabel={ariaLabel} />
        </div>
      )}
    </div>
  );
});

export default FacetMenu;
