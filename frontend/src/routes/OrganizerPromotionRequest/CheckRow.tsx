import type { ReactNode } from 'react';
import styles from './OrganizerPromotionRequest.module.css';

interface CheckRowProps {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  invalid?: boolean;
  children: ReactNode;
}

/** A sharp checkbox row: the native input stays focusable and in the a11y tree
 * (it sits invisibly over the box); the box beside it is the visual. The text
 * is the input's label and may hold a link. */
export default function CheckRow({ id, checked, onChange, invalid, children }: CheckRowProps) {
  return (
    <div className={styles.chkRow}>
      <input
        id={id}
        type="checkbox"
        className={styles.chkInput}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-invalid={invalid || undefined}
      />
      <span className={styles.chkBox} aria-hidden="true">
        <svg className={styles.chkMark} viewBox="0 0 14 14">
          <path d="M2 7.5l3.5 3.5L12 3.5" />
        </svg>
      </span>
      <label htmlFor={id} className={styles.chkText}>{children}</label>
    </div>
  );
}
