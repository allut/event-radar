import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { useLocalePath } from '../../hooks/useLocalePath';
import DialMark from '../DialMark';
import styles from '../shared/Bar.module.css';

interface BarLogoProps {
  locale: string;
  /** Organizer phone bar: the wordmark is dropped, so the link needs its own name. */
  markOnlyOnPhone?: boolean;
}

// Every route mounts its own bar, so a plain CSS animation would replay on
// every navigation. The Dial's intro plays on the first bar mount per page load.
let introPlayed = false;

export default function BarLogo({ locale, markOnlyOnPhone }: BarLogoProps) {
  const localePath = useLocalePath();
  const [intro] = useState(() => !introPlayed);
  useEffect(() => {
    introPlayed = true;
  }, []);
  const brand = t('brand', locale);
  const split = brand.lastIndexOf(' ');
  return (
    <Link
      to={localePath(ROUTES.home)}
      className={cx(styles.logo, markOnlyOnPhone && styles.logoMarkOnlyPhone)}
      aria-label={markOnlyOnPhone ? brand : undefined}
    >
      <DialMark animated={intro} />
      <span className={styles.word}>
        {split === -1 ? brand : <>{brand.slice(0, split)} <em>{brand.slice(split + 1)}</em></>}
      </span>
    </Link>
  );
}
