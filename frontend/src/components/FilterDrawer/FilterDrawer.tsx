import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { t, ti } from '../../i18n';
import styles from './FilterDrawer.module.css';

interface FilterDrawerProps {
  open: boolean;
  onClose: () => void;
  onClear: () => void;
  activeCount: number;
  resultCount: number;
  locale: string;
  children: ReactNode;
}

/** Mobile bottom-sheet: "Filters (n)" trigger lives in the caller (Explore.tsx);
 * this renders the overlay + sliding panel once opened. Facet controls inside
 * apply live (matches desktop) — the footer buttons are close-only. */
export default function FilterDrawer({
  open,
  onClose,
  onClear,
  activeCount,
  resultCount,
  locale,
  children,
}: FilterDrawerProps) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label={t('filters', locale)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h2 className={styles.title}>
            {activeCount > 0 ? `${t('filters', locale)} (${activeCount})` : t('filters', locale)}
          </h2>
          <button type="button" className={styles.clearBtn} onClick={onClear}>
            {t('filters_clear', locale)}
          </button>
        </div>

        <div className={styles.body}>{children}</div>

        <div className={styles.footer}>
          <button type="button" className={styles.showResultsBtn} onClick={onClose}>
            {ti('filters_show_results', locale, { count: String(resultCount) })}
          </button>
        </div>
      </div>
    </div>
  );
}
