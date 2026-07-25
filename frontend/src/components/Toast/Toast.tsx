import { UI_STATE } from '../../constants';
import styles from './Toast.module.css';

interface ToastProps {
  status: typeof UI_STATE.success | typeof UI_STATE.error;
  message: string;
}

export default function Toast({ status, message }: ToastProps) {
  if (status === UI_STATE.success) {
    return <div className={styles.toastSuccess} role="status">{message}</div>;
  }
  return <div className={styles.toastError} role="alert">{message}</div>;
}
