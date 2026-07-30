import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { getLocale, setLocale } from '../../lib/auth';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useOrganizerEventForm } from '../../hooks/useOrganizerEventForm';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import SegmentedControl from '../../components/SegmentedControl';
import { t } from '../../i18n';
import {
  CATEGORIES, CONTENT_LANG_ORDER, DEFAULT_CURRENCY, EUR_SYMBOL, LOCALES,
  ORGANIZER_BASE_CONTENT_LANG, ORGANIZER_IMAGE_ACCEPT, ORGANIZER_TEXTAREA_ROWS,
  type ContentLang,
} from '../../constants';
import { safeUrl } from '../../utils';
import styles from './EventSubmit.module.css';

interface ContentSlot {
  title: string;
  setTitle: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  importantInfo: string;
  setImportantInfo: (v: string) => void;
  hasContent: boolean;
}

export default function EventSubmit() {
  const params = useParams();
  const eventId = params.id ? Number(params.id) : undefined;
  const [locale, setLocaleState] = useState(getLocale());
  const handleLogout = useOrganizerLogout();

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    setLocale(code);
  }

  const form = useOrganizerEventForm(locale, eventId);
  const [contentLang, setContentLang] = useState<ContentLang>(ORGANIZER_BASE_CONTENT_LANG);

  const slots: Record<ContentLang, ContentSlot> = {
    et: {
      title: form.title, setTitle: form.setTitle,
      description: form.description, setDescription: form.setDescription,
      importantInfo: form.importantInfo, setImportantInfo: form.setImportantInfo,
      hasContent: Boolean(form.title.trim() || form.description.trim() || form.importantInfo.trim()),
    },
    en: {
      title: form.titleEn, setTitle: form.setTitleEn,
      description: form.descriptionEn, setDescription: form.setDescriptionEn,
      importantInfo: form.importantInfoEn, setImportantInfo: form.setImportantInfoEn,
      hasContent: Boolean(form.titleEn.trim() || form.descriptionEn.trim() || form.importantInfoEn.trim()),
    },
    ru: {
      title: form.titleRu, setTitle: form.setTitleRu,
      description: form.descriptionRu, setDescription: form.setDescriptionRu,
      importantInfo: form.importantInfoRu, setImportantInfo: form.setImportantInfoRu,
      hasContent: Boolean(form.titleRu.trim() || form.descriptionRu.trim() || form.importantInfoRu.trim()),
    },
  };
  const activeSlot = slots[contentLang];
  const langTabOptions = CONTENT_LANG_ORDER.map((code) => ({
    value: code,
    label: LOCALES.find((l) => l.code === code)?.label ?? code.toUpperCase(),
    dot: code !== ORGANIZER_BASE_CONTENT_LANG && slots[code].hasContent,
  }));

  return (
    <div className={styles.page}>
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <h1 className={styles.title}>
          {form.isEditMode ? t('organizer_edit_title', locale) : t('organizer_submit_title', locale)}
        </h1>

        <form onSubmit={form.submit} className={styles.form} noValidate>
          <div className={styles.contentGroup}>
            <div className={styles.contentHead}>
              <h2 className={styles.contentEyebrow}>{t('organizer_content_heading', locale)}</h2>
              <SegmentedControl
                variant="dial"
                options={langTabOptions}
                value={contentLang}
                onChange={(v) => setContentLang(v as ContentLang)}
                ariaLabel={t('organizer_language_tabs_label', locale)}
              />
            </div>

            <label className={styles.label} htmlFor="content_title">
              {t('organizer_field_title', locale)}
            </label>
            <input
              id="content_title"
              type="text"
              className={styles.input}
              value={activeSlot.title}
              onChange={(e) => activeSlot.setTitle(e.target.value)}
              disabled={form.isSubmitting}
              required={contentLang === ORGANIZER_BASE_CONTENT_LANG}
            />

            <label className={styles.label} htmlFor="content_description">
              {t('organizer_field_description', locale)}
            </label>
            <textarea
              id="content_description"
              className={styles.textarea}
              value={activeSlot.description}
              onChange={(e) => activeSlot.setDescription(e.target.value)}
              rows={ORGANIZER_TEXTAREA_ROWS}
              disabled={form.isSubmitting}
            />

            <label className={styles.label} htmlFor="content_important_info">
              {t('organizer_field_important_info', locale)}
            </label>
            <textarea
              id="content_important_info"
              className={styles.textarea}
              value={activeSlot.importantInfo}
              onChange={(e) => activeSlot.setImportantInfo(e.target.value)}
              rows={ORGANIZER_TEXTAREA_ROWS}
              disabled={form.isSubmitting}
            />
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="starts_at">{t('organizer_field_starts_at', locale)}</label>
              <input
                id="starts_at"
                type="datetime-local"
                className={styles.input}
                value={form.startsAt}
                onChange={(e) => form.setStartsAt(e.target.value)}
                disabled={form.isSubmitting}
                required
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="ends_at">{t('organizer_field_ends_at', locale)}</label>
              <input
                id="ends_at"
                type="datetime-local"
                className={styles.input}
                value={form.endsAt}
                onChange={(e) => form.setEndsAt(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="venue_name">{t('organizer_field_venue_name', locale)}</label>
              <input
                id="venue_name"
                type="text"
                className={styles.input}
                value={form.venueName}
                onChange={(e) => form.setVenueName(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="venue_address">{t('organizer_field_venue_address', locale)}</label>
              <input
                id="venue_address"
                type="text"
                className={styles.input}
                value={form.venueAddress}
                onChange={(e) => form.setVenueAddress(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
          </div>

          <label className={styles.label} htmlFor="category">{t('organizer_field_category', locale)}</label>
          <select
            id="category"
            className={styles.input}
            value={form.category}
            onChange={(e) => form.setCategory(e.target.value)}
            disabled={form.isSubmitting}
          >
            <option value="">{t('organizer_category_none', locale)}</option>
            {CATEGORIES.map((slug) => (
              <option key={slug} value={slug}>{t(`category_${slug}`, locale)}</option>
            ))}
          </select>

          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="price_min">
                {t('organizer_field_price_min', locale)} ({DEFAULT_CURRENCY === 'EUR' ? EUR_SYMBOL : DEFAULT_CURRENCY})
              </label>
              <input
                id="price_min"
                type="number"
                min="0"
                step="0.01"
                className={styles.input}
                value={form.priceMin}
                onChange={(e) => form.setPriceMin(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="price_max">
                {t('organizer_field_price_max', locale)} ({DEFAULT_CURRENCY === 'EUR' ? EUR_SYMBOL : DEFAULT_CURRENCY})
              </label>
              <input
                id="price_max"
                type="number"
                min="0"
                step="0.01"
                className={styles.input}
                value={form.priceMax}
                onChange={(e) => form.setPriceMax(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
          </div>

          <label className={styles.label} htmlFor="url">{t('organizer_field_url', locale)}</label>
          <input
            id="url"
            type="url"
            className={styles.input}
            value={form.url}
            onChange={(e) => form.setUrl(e.target.value)}
            disabled={form.isSubmitting}
          />

          <label className={styles.label} htmlFor="image">{t('organizer_field_image', locale)}</label>
          <input
            id="image"
            type="file"
            accept={ORGANIZER_IMAGE_ACCEPT}
            className={styles.fileInput}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) form.uploadImage(file);
            }}
            disabled={form.isSubmitting || form.imageUploading}
          />
          {form.imageUploading && <p className={styles.hint}>{t('organizer_image_uploading', locale)}</p>}
          {form.imageError && <p className={styles.error} role="alert">{form.imageError}</p>}
          {safeUrl(form.imageUrl) && (
            <img src={safeUrl(form.imageUrl) as string} alt="" className={styles.imagePreview} />
          )}

          {form.submitError && (
            <p className={styles.error} role="alert">{form.submitError}</p>
          )}

          <button
            type="submit"
            className={styles.submit}
            disabled={form.isSubmitting || form.imageUploading || !form.title.trim() || !form.startsAt}
          >
            {form.isSubmitting
              ? <span className={styles.spinner} aria-label={t('sending', locale)} />
              : form.isEditMode ? t('organizer_save_button', locale) : t('organizer_submit_button', locale)}
          </button>
        </form>
      </main>
    </div>
  );
}
