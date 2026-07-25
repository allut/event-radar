import type { ReactNode } from 'react';
import { UI_STATE } from '../../constants';
import styles from './PageState.module.css';

interface PageStateProps {
  kind: typeof UI_STATE.loading | typeof UI_STATE.error;
  message: string;
  action?: ReactNode;
  inline?: boolean;
}

export default function PageState({ kind, message, action, inline = false }: PageStateProps) {
  return (
    <div className={inline ? styles.inline : styles.centered}>
      {kind === UI_STATE.loading ? (
        <span className={styles.spinner} aria-label={message} />
      ) : (
        <p className={styles.errorMsg}>{message}</p>
      )}
      {action}
    </div>
  );
}
