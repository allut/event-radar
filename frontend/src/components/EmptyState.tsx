import styles from './EmptyState.module.css';

interface EmptyStateProps {
  icon: string;
  title: string;
  message: string;
  hint?: string;
}

export default function EmptyState({ icon, title, message, hint }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon} aria-hidden>{icon}</div>
      <h2 className={styles.emptyTitle}>{title}</h2>
      <p className={styles.emptyMsg}>{message}</p>
      {hint && <p className={styles.emptyHint}>{hint}</p>}
    </div>
  );
}
