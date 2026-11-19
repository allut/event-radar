import { t } from '../../../i18n';
import GoogleGMark from './GoogleGMark';
import styles from './GoogleSignInButton.module.css';

interface GoogleSignInButtonProps {
  href: string;
  locale: string;
}

/** Plain top-level-navigation link to the backend's OAuth `start` endpoint —
 * no client-side OAuth logic, no state handling in JS. Reused
 * verbatim by the consumer track (#297) via its own `href`. */
export default function GoogleSignInButton({ href, locale }: GoogleSignInButtonProps) {
  return (
    <a href={href} className={styles.button}>
      <GoogleGMark />
      <span>{t('auth.googleSignIn.buttonLabel', locale)}</span>
    </a>
  );
}
