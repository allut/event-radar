import { useState } from 'react';
import { t } from '../../i18n';
import { ANALYTICS_EVENTS, SIGN_IN_TRIGGER_COPY, type SignInTrigger } from '../../constants';
import { trackEvent } from '../../lib/gtag';
import Modal from '../Modal';
import MagicLinkForm from '../MagicLinkForm';
import styles from './SignInModal.module.css';

interface SignInModalProps {
  open: boolean;
  onClose: () => void;
  /** null while closed — the copy variant + `trigger` analytics param for
   * whichever save/thumbs/for-you control opened this. */
  trigger: SignInTrigger | null;
  locale: string;
}

/** Route-level sign-in upsell modal for anonymous /explore visitors (issue
 * #235). Wraps Modal + MagicLinkForm unchanged — submit tracking below
 * relies on the native 'submit' event bubbling up from MagicLinkForm's
 * <form> into this component's wrapper div, since MagicLinkForm itself must
 * not be touched. The pending action (which card, which signal) is
 * deliberately not remembered anywhere: closing or submitting just closes
 * the modal, nothing is replayed after sign-in. `signin_modal_open` is
 * tracked by the caller (Explore) at the point it decides to actually open
 * the modal — see requestSignIn there. */
export default function SignInModal({ open, onClose, trigger, locale }: SignInModalProps) {
  // Resets `submitted` whenever the trigger prop changes (including the
  // null it settles to on close) — React's documented "adjusting state
  // during render" pattern, same one Explore.tsx uses for its search input
  // sync, so no effect (and no setState-in-effect) is needed here.
  const [trackedTrigger, setTrackedTrigger] = useState<SignInTrigger | null>(trigger);
  const [submitted, setSubmitted] = useState(false);
  if (trigger !== trackedTrigger) {
    setTrackedTrigger(trigger);
    setSubmitted(false);
  }

  function handleClose() {
    if (!submitted && trigger) {
      trackEvent(ANALYTICS_EVENTS.signinModalDismiss, { trigger });
    }
    onClose();
  }

  function handleFormSubmit() {
    setSubmitted(true);
    if (trigger) trackEvent(ANALYTICS_EVENTS.signinModalSubmit, { trigger });
  }

  if (!trigger) return null;
  const copy = SIGN_IN_TRIGGER_COPY[trigger];

  return (
    <Modal open={open} onClose={handleClose} title={t('sign_in', locale)} locale={locale}>
      <p className={styles.heading}>{t(copy.headingKey, locale)}</p>
      <p className={styles.body}>{t(copy.bodyKey, locale)}</p>
      {/* The native 'submit' event bubbles, so this wrapper observes
          MagicLinkForm's <form> submit without needing a prop on it. */}
      <div onSubmit={handleFormSubmit}>
        <MagicLinkForm locale={locale} emailFieldId="signin-modal-email" />
      </div>
    </Modal>
  );
}
