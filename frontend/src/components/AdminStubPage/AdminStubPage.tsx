import styles from './AdminStubPage.module.css';

interface AdminStubPageProps {
  eyebrow: string;
  title: string;
}

// Placeholder for an admin-console screen whose real content ships in a
// later ticket (issue #154's nav lists all 7 screens up front — see
// AdminShell/ADMIN_NAV_ITEMS — even though only Dashboard has real content
// yet). Keeps the route/nav entry live and correctly guarded without
// building functionality that belongs to a different ticket.
export default function AdminStubPage({ eyebrow, title }: AdminStubPageProps) {
  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h1 className={styles.title}>{title}</h1>
      </div>
      <div className={styles.panel}>
        <p className={styles.stub}>This screen ships in a later ticket.</p>
      </div>
    </div>
  );
}
