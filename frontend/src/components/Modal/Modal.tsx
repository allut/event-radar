import { useEffect, useId, useRef, type ReactNode } from 'react';
import { t } from '../../i18n';
import styles from './Modal.module.css';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  locale: string;
  children: ReactNode;
  /** Admin-console register: system font title, never the display serif. */
  admin?: boolean;
}

/** First Modal in this codebase (issue #128) — overlay + centered panel,
 * Escape-to-close, backdrop-click-to-close, focus moved to the panel on open. */
export default function Modal({ open, onClose, title, locale, children, admin }: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className={styles.overlay} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={styles.header}>
          <h2 id={titleId} className={admin ? styles.titleAdmin : styles.title}>{title}</h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label={t('close', locale)}>
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
