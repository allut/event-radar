import { StatusCodes } from 'http-status-codes';
import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import { t } from '../../i18n';
import { ROUTES } from '../../constants';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import SeoTags from '../../components/SeoTags';
import styles from './NotFound.module.css';

export default function NotFound() {
  const locale = getLocale();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('not_found_title', locale);
  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <div className={styles.card}>
        <div className={styles.code} aria-hidden>{StatusCodes.NOT_FOUND}</div>
        <h1 className={styles.title}>{t('not_found_title', locale)}</h1>
        <p className={styles.msg}>{t('not_found_msg', locale)}</p>
        <Link to={localePath(ROUTES.home)} className={styles.backLink}>{t('not_found_back', locale)}</Link>
      </div>
    </div>
  );
}
