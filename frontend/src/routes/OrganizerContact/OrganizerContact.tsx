import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useOrganizerContactSubmit } from '../../hooks/useOrganizerContactSubmit';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { Link } from 'react-router-dom';
import { useLocalePath } from '../../hooks/useLocalePath';
import { UI_STATE, CONTACT_TEXTAREA_ROWS } from '../../constants/core';
import { ROUTES, FAQ_ORGANIZERS_HASH } from '../../constants/routes';
import { t } from '../../i18n';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerContact.module.css';

export default function OrganizerContact() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('organizer_contact_title', locale);
  const { message, setMessage, state, errorMsg, submit, reset } = useOrganizerContactSubmit(locale);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <h1 className={styles.title}>{t('organizer_contact_title', locale)}</h1>
        <p className={styles.body}>{t('organizer_contact_intro', locale)}</p>
        <p className={styles.hint}>
          <Link to={localePath(`${ROUTES.faq}${FAQ_ORGANIZERS_HASH}`)}>{t('organizer_contact_faq_link', locale)}</Link>
        </p>

        {state === UI_STATE.success ? (
          <div className={styles.success} role="status">
            <div className={styles.checkCircle} aria-hidden>✓</div>
            <p className={styles.successTitle}>{t('organizer_contact_success_title', locale)}</p>
            <p className={styles.successBody}>{t('organizer_contact_success_body', locale)}</p>
            <button className={styles.resend} onClick={reset}>
              {t('contact_send_another', locale)}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className={styles.form} noValidate>
            <label className={styles.label} htmlFor="organizer-contact-message">
              {t('organizer_contact_message_label', locale)}
            </label>
            <textarea
              id="organizer-contact-message"
              className={styles.textarea}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={CONTACT_TEXTAREA_ROWS}
              disabled={state === UI_STATE.loading}
              required
            />

            {state === UI_STATE.error && (
              <p className={styles.error} role="alert">{errorMsg}</p>
            )}

            <button
              type="submit"
              className={styles.submit}
              disabled={state === UI_STATE.loading || !message.trim()}
            >
              {state === UI_STATE.loading
                ? <span className={styles.spinner} aria-label={t('sending', locale)} />
                : t('organizer_contact_send', locale)}
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
