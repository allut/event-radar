import { useState } from 'react';
import { cx, fileNameFromUrl, safeUrl } from '../../utils';
import styles from './FileField.module.css';

interface FileFieldProps {
  id: string;
  accept: string;
  onSelect: (file: File) => void;
  onClear: () => void;
  previewUrl: string;
  uploading?: boolean;
  disabled?: boolean;
  chooseLabel: string;
  replaceLabel: string;
  emptyLabel: string;
  uploadingLabel: string;
  removeLabel: string;
}

const RemoveIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
);

/** Field-shaped image upload control — themed replacement for a raw
 * `<input type="file">`. Matches the input/DatePicker/SelectField chrome
 * contract: a raised bordered row with a pick button, filename/state text,
 * and a remove action, plus the image preview folded in below. */
export default function FileField({
  id, accept, onSelect, onClear, previewUrl, uploading = false, disabled = false,
  chooseLabel, replaceLabel, emptyLabel, uploadingLabel, removeLabel,
}: FileFieldProps) {
  const [fileName, setFileName] = useState('');
  const safePreview = safeUrl(previewUrl);
  const displayName = fileName || (previewUrl ? fileNameFromUrl(previewUrl) : '');
  const hasFile = Boolean(previewUrl);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      setFileName(file.name);
      onSelect(file);
    }
    // Reset so re-picking the same file re-fires onChange.
    e.target.value = '';
  }

  function handleClear() {
    setFileName('');
    onClear();
  }

  return (
    <div>
      <div className={styles.field} data-disabled={disabled || undefined}>
        <label className={cx(styles.pickButton, disabled && styles.pickButtonDisabled)} htmlFor={id}>
          {hasFile ? replaceLabel : chooseLabel}
        </label>
        <input
          id={id}
          type="file"
          accept={accept}
          className={styles.srOnly}
          onChange={handleChange}
          disabled={disabled}
        />
        {uploading ? (
          <span className={styles.fileName}>
            <span className={styles.spinner} aria-hidden />
            <span className={styles.fileNameText}>{uploadingLabel}</span>
          </span>
        ) : (
          <span className={cx(styles.fileName, !displayName && styles.fileNamePlaceholder)}>
            <span className={styles.fileNameText}>{displayName || emptyLabel}</span>
          </span>
        )}
        {hasFile && !uploading && (
          <button
            type="button"
            className={styles.removeButton}
            aria-label={removeLabel}
            onClick={handleClear}
            disabled={disabled}
          >
            <RemoveIcon />
          </button>
        )}
      </div>
      {safePreview && (
        <img src={safePreview} alt="" className={styles.preview} />
      )}
    </div>
  );
}
