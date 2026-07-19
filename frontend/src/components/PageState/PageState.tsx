import type { ReactNode } from 'react';
import styles from './PageState.module.css';

interface PageStateProps {
  kind: 'loading' | 'error';
  message: string;
  action?: ReactNode;
  inline?: boolean;
}

export default function PageState({ kind, message, action, inline = false }: PageStateProps) {
  return (
    <div className={inline ? styles.inline : styles.centered}>
      {kind === 'loading' ? (
        <span className={styles.spinner} aria-label={message} />
      ) : (
        <p className={styles.errorMsg}>{message}</p>
      )}
      {action}
    </div>
  );
}
