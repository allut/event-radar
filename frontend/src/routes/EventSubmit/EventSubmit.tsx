import { useMemo, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useOrganizerEventForm } from '../../hooks/useOrganizerEventForm';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import SegmentedControl from '../../components/SegmentedControl';
import DatePicker from '../../components/DatePicker';
import SelectField from '../../components/SelectField';
import FileField from '../../components/FileField';
import { t, ti } from '../../i18n';
import {
  CATEGORIES, CONTENT_LANG_ORDER, DEFAULT_CURRENCY, LOCALE_EN, LOCALE_ET, LOCALE_RU, LOCALES,
  ORGANIZER_BASE_CONTENT_LANG, ORGANIZER_IMAGE_ACCEPT, ORGANIZER_TEXTAREA_ROWS,
  PRICE_INPUT_MIN, PRICE_INPUT_STEP,
  type ContentLang, type ContentMarkerState,
} from '../../constants';
import { currencySymbol, titleWithBrand } from '../../utils';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import SeoTags from '../../components/SeoTags';
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
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();

  const form = useOrganizerEventForm(locale, eventId);
  const [contentLang, setContentLang] = useState<ContentLang>(ORGANIZER_BASE_CONTENT_LANG);
  const { pathname } = useLocation();
  const seoMeta = useSeoMeta({
    title: titleWithBrand(t(form.isEditMode ? 'organizer_edit_title' : 'organizer_submit_title', locale), locale),
    locale,
    path: pathname,
  });

  // Re-trims all 9 text fields (multi-KB organizer prose) only when one of
  // them actually changes, not on every unrelated keystroke (price, venue, etc).
  const slots: Record<ContentLang, ContentSlot> = useMemo(() => ({
    [LOCALE_ET]: {
      title: form.title, setTitle: form.setTitle,
      description: form.description, setDescription: form.setDescription,
      importantInfo: form.importantInfo, setImportantInfo: form.setImportantInfo,
      hasContent: Boolean(form.title.trim() || form.description.trim() || form.importantInfo.trim()),
    },
    [LOCALE_EN]: {
      title: form.titleEn, setTitle: form.setTitleEn,
      description: form.descriptionEn, setDescription: form.setDescriptionEn,
      importantInfo: form.importantInfoEn, setImportantInfo: form.setImportantInfoEn,
      hasContent: Boolean(form.titleEn.trim() || form.descriptionEn.trim() || form.importantInfoEn.trim()),
    },
    [LOCALE_RU]: {
      title: form.titleRu, setTitle: form.setTitleRu,
      description: form.descriptionRu, setDescription: form.setDescriptionRu,
      importantInfo: form.importantInfoRu, setImportantInfo: form.setImportantInfoRu,
      hasContent: Boolean(form.titleRu.trim() || form.descriptionRu.trim() || form.importantInfoRu.trim()),
    },
  }), [
    form.title, form.setTitle, form.description, form.setDescription, form.importantInfo, form.setImportantInfo,
    form.titleEn, form.setTitleEn, form.descriptionEn, form.setDescriptionEn, form.importantInfoEn, form.setImportantInfoEn,
    form.titleRu, form.setTitleRu, form.descriptionRu, form.setDescriptionRu, form.importantInfoRu, form.setImportantInfoRu,
  ]);
  const activeSlot = slots[contentLang];
  const contentLangLabel = (code: ContentLang) =>
    LOCALES.find((l) => l.code === code)?.label ?? code.toUpperCase();
  // Field-by-field against the ET base slot.
  const markerState = (code: ContentLang): ContentMarkerState => {
    const slot = slots[code];
    if (!slot.hasContent) return 'empty';
    if (code === ORGANIZER_BASE_CONTENT_LANG) return 'matched';
    const base = slots[ORGANIZER_BASE_CONTENT_LANG];
    const missesBaseField =
      (base.title.trim() && !slot.title.trim()) ||
      (base.description.trim() && !slot.description.trim()) ||
      (base.importantInfo.trim() && !slot.importantInfo.trim());
    return missesBaseField ? 'partial' : 'matched';
  };
  const langTabOptions = CONTENT_LANG_ORDER.map((code) => {
    const state = markerState(code);
    return {
      value: code,
      label: contentLangLabel(code),
      marker: { state, stateLabel: t(`organizer_lang_state_${state}`, locale) },
    };
  });
  // Rebuilding this 14-option list (+14 t() lookups) only needs to happen when
  // the locale changes, not on every keystroke elsewhere in the form.
  const categoryOptions = useMemo(
    () => CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) })),
    [locale],
  );
  const langField = (key: string) =>
    ti('organizer_field_lang_suffix', locale, {
      field: t(key, locale),
      lang: contentLangLabel(contentLang),
    });

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
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
            <p className={styles.contentHint}>
              {ti('organizer_lang_hint', locale, { base: contentLangLabel(ORGANIZER_BASE_CONTENT_LANG) })}
            </p>

            <label className={styles.label} htmlFor="content_title">
              {langField('organizer_field_title')}
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
              {langField('organizer_field_description')}
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
              {langField('organizer_field_important_info')}
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
              <DatePicker
                id="starts_at"
                value={form.startsAt}
                onChange={form.setStartsAt}
                locale={locale}
                disabled={form.isSubmitting}
                required
                ariaLabel={t('organizer_field_starts_at', locale)}
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="ends_at">{t('organizer_field_ends_at', locale)}</label>
              <DatePicker
                id="ends_at"
                value={form.endsAt}
                onChange={form.setEndsAt}
                locale={locale}
                disabled={form.isSubmitting}
                min={form.startsAt}
                ariaLabel={t('organizer_field_ends_at', locale)}
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
          <SelectField
            id="category"
            value={form.category}
            options={categoryOptions}
            onChange={form.setCategory}
            placeholder={t('organizer_category_none', locale)}
            ariaLabel={t('organizer_field_category', locale)}
            disabled={form.isSubmitting}
          />

          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="price_min">
                {t('organizer_field_price_min', locale)} ({currencySymbol(DEFAULT_CURRENCY)})
              </label>
              <input
                id="price_min"
                type="number"
                min={PRICE_INPUT_MIN}
                step={PRICE_INPUT_STEP}
                className={styles.input}
                value={form.priceMin}
                onChange={(e) => form.setPriceMin(e.target.value)}
                disabled={form.isSubmitting}
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.label} htmlFor="price_max">
                {t('organizer_field_price_max', locale)} ({currencySymbol(DEFAULT_CURRENCY)})
              </label>
              <input
                id="price_max"
                type="number"
                min={PRICE_INPUT_MIN}
                step={PRICE_INPUT_STEP}
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
          <FileField
            id="image"
            accept={ORGANIZER_IMAGE_ACCEPT}
            onSelect={form.uploadImage}
            onClear={form.clearImage}
            previewUrl={form.imageUrl}
            uploading={form.imageUploading}
            disabled={form.isSubmitting || form.imageUploading}
            chooseLabel={t('organizer_image_choose', locale)}
            replaceLabel={t('organizer_image_replace', locale)}
            emptyLabel={t('organizer_image_none', locale)}
            uploadingLabel={t('organizer_image_uploading', locale)}
            removeLabel={t('organizer_image_remove', locale)}
          />
          {form.imageError && <p className={styles.error} role="alert">{form.imageError}</p>}

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
