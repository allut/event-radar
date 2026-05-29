import { StatusCodes } from 'http-status-codes';
import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import { t } from '../../i18n';
import styles from './NotFound.module.css';

export default function NotFound() {
  const locale = getLocale();
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.code} aria-hidden>{StatusCodes.NOT_FOUND}</div>
        <h1 className={styles.title}>{t('not_found_title', locale)}</h1>
        <p className={styles.msg}>{t('not_found_msg', locale)}</p>
        <Link to="/" className={styles.backLink}>{t('not_found_back', locale)}</Link>
      </div>
    </div>
  );
}
