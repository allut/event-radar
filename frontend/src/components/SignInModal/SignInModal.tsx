import { t } from '../../i18n';
import { SIGN_IN_TRIGGER_COPY, type SignInTrigger } from '../../constants/explore';
import Modal from '../Modal';
import MagicLinkForm from '../MagicLinkForm';
import styles from './SignInModal.module.css';

interface SignInModalProps {
  open: boolean;
  onClose: () => void;
  /** null while closed — the copy variant for
   * whichever save/thumbs/for-you control opened this. */
  trigger: SignInTrigger | null;
  locale: string;
}

/** Route-level sign-in upsell modal for anonymous /explore visitors (issue
 * #235). Wraps Modal + MagicLinkForm unchanged. The pending action (which
 * card, which signal) is deliberately not remembered anywhere: closing or
 * submitting just closes the modal, nothing is replayed after sign-in. */
export default function SignInModal({ open, onClose, trigger, locale }: SignInModalProps) {
  if (!trigger) return null;
  const copy = SIGN_IN_TRIGGER_COPY[trigger];

  return (
    <Modal open={open} onClose={onClose} title={t('sign_in', locale)} locale={locale}>
      <p className={styles.heading}>{t(copy.headingKey, locale)}</p>
      <p className={styles.body}>{t(copy.bodyKey, locale)}</p>
      <MagicLinkForm locale={locale} emailFieldId="signin-modal-email" />
    </Modal>
  );
}
