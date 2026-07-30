import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useAuth } from '../../hooks/useAuth';
import { useLogout } from '../../hooks/useLogout';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useContactSubmit } from '../../hooks/useContactSubmit';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { QUERY_KEYS, UI_STATE, CONTACT_TEXTAREA_ROWS } from '../../constants';
import { t } from '../../i18n';
import TopBar from '../../components/TopBar';
import styles from './Contact.module.css';

export default function Contact() {
  const authed = useAuth();
  const isOrganizer = useOrganizerAuth();
  const handleLogout = useLogout();
  const { locale, handleLocaleChange } = useLocaleMutation();
  const {
    name, setName,
    email, setEmail,
    message, setMessage,
    setWebsite,
    state, errorMsg, submit, reset,
  } = useContactSubmit(locale);

  // Prefill from the signed-in user's account so they don't retype an email
  // already on file; shares the Settings page's /users/me query cache.
  const { data: me } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<{ email: string }>('/users/me'),
    enabled: authed,
  });

  // One-shot prefill: only on the first arrival of the fetched email, so a
  // background refetch (e.g. window refocus) can't clobber an in-progress edit.
  const prefilled = useRef(false);
  useEffect(() => {
    if (me?.email && !prefilled.current) {
      prefilled.current = true;
      setEmail(me.email);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  return (
    <div className={styles.page}>
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        authed={authed}
      />

      <main className={styles.main}>
        <h1 className={styles.title}>{t('contact_title', locale)}</h1>
        <p className={styles.body}>{t('contact_intro', locale)}</p>
        <p className={styles.organizerHint}>
          <Link to={isOrganizer ? '/organizer/dashboard' : '/organizer/login'}>
            {t('organizer_entry_link', locale)}
          </Link>
        </p>

        {state === UI_STATE.success ? (
          <div className={styles.success} role="status">
            <div className={styles.checkCircle}>✓</div>
            <p className={styles.successTitle}>{t('contact_success_title', locale)}</p>
            <p className={styles.successBody}>{t('contact_success_body', locale)}</p>
            <button className={styles.resend} onClick={reset}>
              {t('contact_send_another', locale)}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className={styles.form} noValidate>
            <label className={styles.label} htmlFor="name">{t('contact_name_label', locale)}</label>
            <input
              id="name"
              type="text"
              className={styles.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              disabled={state === UI_STATE.loading}
              required
            />

            <label className={styles.label} htmlFor="email">{t('email_label', locale)}</label>
            <input
              id="email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('email_placeholder', locale)}
              autoComplete="email"
              disabled={state === UI_STATE.loading}
              required
            />

            <label className={styles.label} htmlFor="message">{t('contact_message_label', locale)}</label>
            <textarea
              id="message"
              className={styles.textarea}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={CONTACT_TEXTAREA_ROWS}
              disabled={state === UI_STATE.loading}
              required
            />

            {/* Honeypot — hidden from sighted users and excluded from the tab
                order; real visitors never see or fill this in. */}
            <input
              type="text"
              name="website"
              className={styles.honeypot}
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
              onChange={(e) => setWebsite(e.target.value)}
            />

            {state === UI_STATE.error && (
              <p className={styles.error} role="alert">{errorMsg}</p>
            )}

            <button
              type="submit"
              className={styles.submit}
              disabled={state === UI_STATE.loading || !name.trim() || !email.trim() || !message.trim()}
            >
              {state === UI_STATE.loading
                ? <span className={styles.spinner} aria-label={t('sending', locale)} />
                : t('contact_send', locale)}
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
