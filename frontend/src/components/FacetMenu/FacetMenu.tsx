import { useEffect } from 'react';
import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { MOBILE_BREAKPOINT_PX } from '../../constants';
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
 * Popover options reuse the shared Chip pill component. */
export default function FacetMenu({
  label,
  options,
  selected,
  onToggle,
  ariaLabel,
  variant = 'button',
}: FacetMenuProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef } = useDropdown();
  const hasSelection = selected.length > 0;

  // Fixed-position popover on mobile (see .pop's mobile override) needs its
  // `top` computed from the trigger's viewport position — CSS alone can't
  // express that once the panel leaves the trigger's positioned ancestor.
  // Re-synced on scroll/resize so it doesn't drift from the trigger while open.
  useEffect(() => {
    if (!open || !popRef.current || !triggerRef.current) return;
    if (!window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX}px)`).matches) return;

    function syncTop() {
      const bottom = triggerRef.current!.getBoundingClientRect().bottom;
      popRef.current!.style.setProperty('--facet-pop-top', `calc(${bottom}px + var(--space-0-45))`);
    }

    syncTop();
    window.addEventListener('scroll', syncTop, true);
    window.addEventListener('resize', syncTop);
    return () => {
      window.removeEventListener('scroll', syncTop, true);
      window.removeEventListener('resize', syncTop);
    };
  }, [open, popRef, triggerRef]);

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
}
