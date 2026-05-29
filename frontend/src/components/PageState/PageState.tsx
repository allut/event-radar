import type { ReactNode } from 'react';
import styles from './PageState.module.css';

interface PageStateProps {
  kind: 'loading' | 'error';
  message: string;
  action?: ReactNode;
}

export default function PageState({ kind, message, action }: PageStateProps) {
  return (
    <div className={styles.centered}>
      {kind === 'loading' ? (
        <span className={styles.spinner} aria-label={message} />
      ) : (
        <p className={styles.errorMsg}>{message}</p>
      )}
      {action}
    </div>
  );
}
