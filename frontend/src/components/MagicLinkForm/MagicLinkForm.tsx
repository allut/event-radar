import { t, ti } from '../../i18n';
import { cx } from '../../utils';
import { MAGIC_LINK_EXPIRY_MINUTES, UI_STATE } from '../../constants';
import { useMagicLinkRequest } from '../../hooks/useMagicLinkRequest';
import styles from './MagicLinkForm.module.css';

interface MagicLinkFormProps {
  locale: string;
  requestPath?: string;
  /** Posts requestPath through the organizer-scoped API client (own session
   * token, own 401 redirect) instead of the consumer one. */
  organizer?: boolean;
  /** id shared between the email <label htmlFor> and <input id> — callers
   * need distinct ids when more than one instance can mount at once. */
  emailFieldId: string;
  /** Login's original design fades the success block in; OrganizerLogin's didn't. */
  successAnimated?: boolean;
}

/** Email input + submit + success/resend block shared by Login and
 * OrganizerLogin — parameterized by requestPath (which auth track's
 * request-link endpoint to POST) and the email field's id. Page chrome
 * (card/header/tagline/footer links) stays in each route, since those
 * differ per track. */
export default function MagicLinkForm({ locale, requestPath, organizer = false, emailFieldId, successAnimated = false }: MagicLinkFormProps) {
  const { email, setEmail, state, errorMsg, submit, reset } = useMagicLinkRequest(locale, requestPath, organizer);

  if (state === UI_STATE.success) {
    return (
      <div className={cx(styles.success, successAnimated && styles.successAnimated)} role="status">
        <div className={styles.checkCircle}>✓</div>
        <p className={styles.successMsg}>
          {t('check_inbox', locale)} <strong>{email}</strong>
        </p>
        <p className={styles.successHint}>
          {ti('link_expires', locale, { minutes: String(MAGIC_LINK_EXPIRY_MINUTES) })}
        </p>
        <button className={styles.resend} onClick={reset}>
          {t('use_different', locale)}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className={styles.form} noValidate>
      <label className={styles.label} htmlFor={emailFieldId}>{t('email_label', locale)}</label>
      <input
        id={emailFieldId}
        type="email"
        className={styles.input}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder={t('email_placeholder', locale)}
        autoFocus
        autoComplete="email"
        disabled={state === UI_STATE.loading}
        required
      />

      {state === UI_STATE.error && (
        <p className={styles.error} role="alert">{errorMsg}</p>
      )}

      <button
        type="submit"
        className={styles.submit}
        disabled={state === UI_STATE.loading || !email.trim()}
      >
        {state === UI_STATE.loading
          ? <span className={styles.spinner} aria-label={t('sending', locale)} />
          : t('send_link', locale)}
      </button>
    </form>
  );
}
