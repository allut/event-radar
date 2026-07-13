import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import Chip, { type ChipOption } from '../Chip';
import menuStyles from '../shared/Menu.module.css';
import styles from './FacetMenu.module.css';

interface FacetMenuProps {
  label: string;
  options: ChipOption[];
  selected: string[];
  onToggle: (value: string) => void;
  ariaLabel: string;
}

/** Trigger button + popover for one Explore facet (Category/Vibe/When).
 * Popover options reuse the shared Chip pill component. */
export default function FacetMenu({ label, options, selected, onToggle, ariaLabel }: FacetMenuProps) {
  const { open, setOpen, rootRef, popRef, triggerRef } = useDropdown();
  const hasSelection = selected.length > 0;

  return (
    <div className={menuStyles.menu} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={cx(styles.menuBtn, hasSelection && styles.has)}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
      >
        {hasSelection ? `${label} · ${selected.length}` : label}
        <span className={styles.chev} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={menuStyles.menuPop} ref={popRef}>
          <Chip options={options} selected={selected} onToggle={onToggle} ariaLabel={ariaLabel} />
        </div>
      )}
    </div>
  );
}
