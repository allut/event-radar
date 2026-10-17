import { Link } from 'react-router-dom';
import { t } from '../../i18n';
import { ROUTES } from '../../constants/routes';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from './RankingLink.module.css';

interface RankingLinkProps {
  locale: string;
  /** Placement class from the caller (alignment, margins). */
  className?: string;
}

/** The Ranking disclosure link (UCPD Art. 7(4a)): a quiet text link to /ranking,
 * shown under Explore's results header and the Daily 5 list. */
export default function RankingLink({ locale, className }: RankingLinkProps) {
  const localePath = useLocalePath();
  return (
    <Link to={localePath(ROUTES.ranking)} className={className ? `${styles.link} ${className}` : styles.link}>
      {t('ranking_link', locale)}
    </Link>
  );
}
