import { t } from '../../i18n';
import { useAuth } from '../../hooks/useAuth';
import { useLogout } from '../../hooks/useLogout';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import TopBar from '../TopBar';
import styles from './StaticPage.module.css';

interface StaticPageProps {
  /** i18n key for the page heading. */
  titleKey: string;
  /** i18n keys for the body paragraphs, in order. */
  bodyKeys: string[];
}

/** Presentational shell for the public stub content pages (Privacy, Terms,
 * Contact) the footer links to. Renders the shared TopBar (locale + auth aware)
 * plus a readable prose column, keeping the three route files DRY. Locale
 * handling mirrors EventDetail: useLocaleMutation persists for authed users and
 * falls back to a local-only switch for anonymous visitors. */
export default function StaticPage({ titleKey, bodyKeys }: StaticPageProps) {
  const authed = useAuth();
  const handleLogout = useLogout();
  // No server data to refetch on a locale switch — the page text re-renders off
  // the returned `locale` state — so the invalidation key is an inert sentinel.
  const { locale, handleLocaleChange } = useLocaleMutation();

  return (
    <div className={styles.page}>
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        authed={authed}
      />

      <main className={styles.main}>
        <h1 className={styles.title}>{t(titleKey, locale)}</h1>
        {bodyKeys.map((key) => (
          <p key={key} className={styles.body}>{t(key, locale)}</p>
        ))}
      </main>
    </div>
  );
}
