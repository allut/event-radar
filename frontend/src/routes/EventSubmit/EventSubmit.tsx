import { lazy, Suspense, useMemo, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useOrganizerEventForm } from '../../hooks/useOrganizerEventForm';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import OrganizerProfileNudge from '../../components/OrganizerProfileNudge';
import SegmentedControl from '../../components/SegmentedControl';
import DatePicker from '../../components/DatePicker';
import CategoryPicker from '../../components/CategoryPicker';
import FileField from '../../components/FileField';
import VenuePicker from '../../components/VenuePicker';
import { t, ti } from '../../i18n';
import {
  DEFAULT_CURRENCY,
  LOCALE_EN,
  LOCALE_RU,
  ORGANIZER_MAX_CATEGORIES,
} from '../../_generated/sharedConstants';
import {
  CONTENT_LANG_ORDER,
  LOCALE_ET,
  type ContentLang,
  type ContentMarkerState,
} from '../../constants/core';
import {
  ORGANIZER_BASE_CONTENT_LANG,
  ORGANIZER_IMAGE_ACCEPT,
  PRICE_INPUT_MIN,
  PRICE_INPUT_STEP,
} from '../../constants/organizer';
import { categoryOptions, localeLabel, localizedFieldLabel, titleWithBrand } from '../../utils/locale';
import { hasHtmlContent } from '../../utils/html';
import { currencySymbol } from '../../utils/price';

import { useSeoMeta } from '../../hooks/useSeoMeta';
import SeoTags from '../../components/SeoTags';
import styles from './EventSubmit.module.css';

// Tiptap is a heavy dependency reachable only from the organizer portal — kept
// out of the main consumer-app bundle (Landing/Feed) via its own chunk, same
// rationale as AdminApp.tsx's lazy boundary.
const RichTextEditor = lazy(() => import('../../components/RichTextEditor'));

interface ContentSlot {
  title: string;
  setTitle: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  importantInfo: string;
  setImportantInfo: (v: string) => void;
  hasTitle: boolean;
  hasDescription: boolean;
  hasImportantInfo: boolean;
  hasContent: boolean;
}

// hasHtmlContent runs DOMPurify.sanitize — computed once per slot per render
// here (memoized alongside the slot itself) rather than re-run per field
// inside markerState on every keystroke anywhere in the form.
function makeSlot(
  title: string, setTitle: (v: string) => void,
  description: string, setDescription: (v: string) => void,
  importantInfo: string, setImportantInfo: (v: string) => void,
): ContentSlot {
  const hasTitle = Boolean(title.trim());
  const hasDescription = hasHtmlContent(description);
  const hasImportantInfo = hasHtmlContent(importantInfo);
  return {
    title, setTitle, description, setDescription, importantInfo, setImportantInfo,
    hasTitle, hasDescription, hasImportantInfo,
    hasContent: hasTitle || hasDescription || hasImportantInfo,
  };
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

  // One memo per content slot: a keystroke in one language's fields re-runs
  // hasHtmlContent (a DOMPurify pass) for that slot only, not all three.
  const etSlot = useMemo(() => makeSlot(
    form.title, form.setTitle,
    form.description, form.setDescription,
    form.importantInfo, form.setImportantInfo,
  ), [form.title, form.setTitle, form.description, form.setDescription, form.importantInfo, form.setImportantInfo]);
  const enSlot = useMemo(() => makeSlot(
    form.titleEn, form.setTitleEn,
    form.descriptionEn, form.setDescriptionEn,
    form.importantInfoEn, form.setImportantInfoEn,
  ), [form.titleEn, form.setTitleEn, form.descriptionEn, form.setDescriptionEn, form.importantInfoEn, form.setImportantInfoEn]);
  const ruSlot = useMemo(() => makeSlot(
    form.titleRu, form.setTitleRu,
    form.descriptionRu, form.setDescriptionRu,
    form.importantInfoRu, form.setImportantInfoRu,
  ), [form.titleRu, form.setTitleRu, form.descriptionRu, form.setDescriptionRu, form.importantInfoRu, form.setImportantInfoRu]);
  const slots: Record<ContentLang, ContentSlot> = useMemo(
    () => ({ [LOCALE_ET]: etSlot, [LOCALE_EN]: enSlot, [LOCALE_RU]: ruSlot }),
    [etSlot, enSlot, ruSlot],
  );
  const activeSlot = slots[contentLang];
  // Field-by-field against the ET base slot.
  const markerState = (code: ContentLang): ContentMarkerState => {
    const slot = slots[code];
    if (!slot.hasContent) return 'empty';
    if (code === ORGANIZER_BASE_CONTENT_LANG) return 'matched';
    const base = slots[ORGANIZER_BASE_CONTENT_LANG];
    const missesBaseField =
      (base.hasTitle && !slot.hasTitle) ||
      (base.hasDescription && !slot.hasDescription) ||
      (base.hasImportantInfo && !slot.hasImportantInfo);
    return missesBaseField ? 'partial' : 'matched';
  };
  const langTabOptions = CONTENT_LANG_ORDER.map((code) => {
    const state = markerState(code);
    return {
      value: code,
      label: localeLabel(code),
      marker: { state, stateLabel: t(`organizer_lang_state_${state}`, locale) },
    };
  });
  // Rebuilding this 14-option list (+14 t() lookups) only needs to happen when
  // the locale changes, not on every keystroke elsewhere in the form.
  const categoryOpts = useMemo(() => categoryOptions(locale), [locale]);
  const langField = (key: string) => localizedFieldLabel(key, locale, contentLang);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <OrganizerProfileNudge locale={locale} />
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
              {ti('organizer_lang_hint', locale, { base: localeLabel(ORGANIZER_BASE_CONTENT_LANG) })}
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

            <label className={styles.label} id="content_description_label">
              {langField('organizer_field_description')}
            </label>
            <Suspense fallback={<div className={styles.editorFallback} />}>
              <RichTextEditor
                id="content_description"
                aria-labelledby="content_description_label"
                value={activeSlot.description}
                onChange={activeSlot.setDescription}
                disabled={form.isSubmitting}
                locale={locale}
              />
            </Suspense>

            <label className={styles.label} id="content_important_info_label">
              {langField('organizer_field_important_info')}
            </label>
            <Suspense fallback={<div className={styles.editorFallback} />}>
              <RichTextEditor
                id="content_important_info"
                aria-labelledby="content_important_info_label"
                value={activeSlot.importantInfo}
                onChange={activeSlot.setImportantInfo}
                disabled={form.isSubmitting}
                locale={locale}
              />
            </Suspense>
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

          <VenuePicker
            id="venue"
            value={form.venue}
            onChange={form.setVenue}
            locale={locale}
            contentLang={contentLang}
            disabled={form.isSubmitting}
          />

          <span className={styles.label}>{t('organizer_field_categories', locale)}</span>
          <CategoryPicker
            options={categoryOpts}
            selected={form.categories}
            max={ORGANIZER_MAX_CATEGORIES}
            onToggle={form.toggleCategory}
            ariaLabel={t('organizer_field_categories', locale)}
            locale={locale}
            disabled={form.isSubmitting}
          />
          <span className={styles.hint}>
            {ti('organizer_categories_hint', locale, { max: String(ORGANIZER_MAX_CATEGORIES) })}{' '}
            {ti('organizer_categories_count', locale, {
              count: String(form.categories.length),
              max: String(ORGANIZER_MAX_CATEGORIES),
            })}
          </span>

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
