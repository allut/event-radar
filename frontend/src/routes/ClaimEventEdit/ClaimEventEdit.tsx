import { lazy, Suspense, useMemo } from 'react';
import { useLocation, useParams, useSearchParams } from 'react-router-dom';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useClaimEventEdit } from '../../hooks/useClaimEventEdit';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import DatePicker from '../../components/DatePicker';
import FileField from '../../components/FileField';
import CategoryPicker from '../../components/CategoryPicker';
import { t, ti } from '../../i18n';
import { ORGANIZER_MAX_CATEGORIES } from '../../_generated/sharedConstants';
import { CLAIM_EDIT_LOCALES } from '../../constants/claims';
import { LOCALE_EN, LOCALE_ET } from '../../constants/core';
import { ORGANIZER_IMAGE_ACCEPT } from '../../constants/organizer';
import { EVENT_STATUS } from '../../constants/prerender';
import { categoryOptions, cx, currencySymbol, localizedFieldLabel, titleWithBrand } from '../../utils';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import SeoTags from '../../components/SeoTags';
import styles from './ClaimEventEdit.module.css';

const RichTextEditor = lazy(() => import('../../components/RichTextEditor'));

interface PinTagProps {
  locale: string;
  pinned: boolean;
  onUnpin: () => void;
  unpinning: boolean;
}

function PinTag({ locale, pinned, onUnpin, unpinning }: PinTagProps) {
  if (!pinned) {
    return <span className={styles.syncTag}>{t('claim_edit_synced_badge', locale)}</span>;
  }
  return (
    <div className={styles.fieldHead}>
      <span className={styles.pinTag}>{t('claim_edit_pinned_badge', locale)}</span>
      <button type="button" className={styles.unpinBtn} onClick={onUnpin} disabled={unpinning}>
        {t('claim_edit_unpin', locale)}
      </button>
    </div>
  );
}

export default function ClaimEventEdit() {
  const params = useParams();
  const claimId = Number(params.id);
  const [searchParams] = useSearchParams();
  const parsedEventId = Number(searchParams.get('event_id'));
  const eventId = Number.isFinite(parsedEventId) && parsedEventId > 0 ? parsedEventId : undefined;
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const { pathname } = useLocation();
  const form = useClaimEventEdit(claimId, locale, eventId);
  const seoMeta = useSeoMeta({
    title: titleWithBrand(t('claim_edit_title', locale), locale),
    locale,
    path: pathname,
  });
  const categoryOpts = useMemo(() => categoryOptions(locale), [locale]);

  function renderPin(field: string, fieldLocale?: string) {
    const pinned = form.isPinned(field, fieldLocale);
    const key = fieldLocale ? `${field}:${fieldLocale}` : field;
    return (
      <PinTag
        locale={locale}
        pinned={pinned}
        onUnpin={() => form.unpin(field, fieldLocale)}
        unpinning={form.unpinning === key}
      />
    );
  }

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <div className={styles.eyebrow}>{t('claim_pill_claimed', locale)}</div>
        <h1 className={styles.title}>{t('claim_edit_title', locale)}</h1>
        <p className={styles.intro}>{t('claim_edit_intro', locale)}</p>

        {(form.isLoading || form.isSaving) && (
          <div
            className={styles.overlay}
            role="status"
            aria-label={form.isSaving ? t('claim_edit_saving', locale) : t('loading', locale)}
          >
            <span className={styles.overlaySpinner} />
          </div>
        )}

        {form.isLocked && (
          <div className={styles.locked}>
            <h2 className={styles.lockedTitle}>
              {t(form.isDormant ? 'claim_edit_dormant_title' : 'claim_edit_locked_title', locale)}
            </h2>
            <p className={styles.lockedBody}>
              {t(form.isDormant ? 'claim_edit_dormant_body' : 'claim_edit_locked_body', locale)}
            </p>
          </div>
        )}

        {!form.isLoading && !form.isLocked && form.loadError && (
          <p className={styles.error} role="alert">{form.loadError}</p>
        )}

        {!form.isLoading && !form.isLocked && form.data && (
          <>
            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('claim_edit_section_editable', locale)}</div>
              <div className={styles.fields}>

                {CLAIM_EDIT_LOCALES.map((code) => (
                  <div className={styles.fieldCol} key={`title_${code}`}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} htmlFor={`title_${code}`}>
                        {code === LOCALE_ET
                          ? t('claim_edit_field_title', locale)
                          : localizedFieldLabel('claim_edit_field_title', locale, code)}
                      </label>
                      {renderPin('title', code)}
                    </div>
                    <input
                      id={`title_${code}`}
                      type="text"
                      className={styles.input}
                      value={code === LOCALE_ET ? form.fields.title : code === LOCALE_EN ? form.fields.titleEn : form.fields.titleRu}
                      onChange={(e) => {
                        if (code === LOCALE_ET) form.setField('title', 'title', e.target.value);
                        else if (code === LOCALE_EN) form.setField('titleEn', 'title_en', e.target.value);
                        else form.setField('titleRu', 'title_ru', e.target.value);
                      }}
                    />
                  </div>
                ))}

                {CLAIM_EDIT_LOCALES.map((code) => (
                  <div className={styles.fieldCol} key={`description_${code}`}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} id={`description_${code}_label`}>
                        {code === LOCALE_ET
                          ? t('claim_edit_field_description', locale)
                          : localizedFieldLabel('claim_edit_field_description', locale, code)}
                      </label>
                      {renderPin('description', code)}
                    </div>
                    <Suspense fallback={<div className={styles.editorFallback} />}>
                      <RichTextEditor
                        id={`description_${code}`}
                        aria-labelledby={`description_${code}_label`}
                        value={
                          code === LOCALE_ET
                            ? form.fields.description
                            : code === LOCALE_EN
                              ? form.fields.descriptionEn
                              : form.fields.descriptionRu
                        }
                        onChange={(html) => {
                          if (code === LOCALE_ET) form.setField('description', 'description', html);
                          else if (code === LOCALE_EN) form.setField('descriptionEn', 'description_en', html);
                          else form.setField('descriptionRu', 'description_ru', html);
                        }}
                        locale={locale}
                      />
                    </Suspense>
                  </div>
                ))}

                <div className={styles.fieldRow}>
                  <div className={styles.fieldCol}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} htmlFor="starts_at">{t('claim_edit_field_starts_at', locale)}</label>
                      {renderPin('starts_at')}
                    </div>
                    <DatePicker
                      id="starts_at"
                      value={form.fields.startsAt}
                      onChange={(v) => form.setField('startsAt', 'starts_at', v)}
                      locale={locale}
                      required
                      ariaLabel={t('claim_edit_field_starts_at', locale)}
                    />
                  </div>
                  <div className={styles.fieldCol}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} htmlFor="ends_at">{t('claim_edit_field_ends_at', locale)}</label>
                      {renderPin('ends_at')}
                    </div>
                    <DatePicker
                      id="ends_at"
                      value={form.fields.endsAt}
                      onChange={(v) => form.setField('endsAt', 'ends_at', v)}
                      locale={locale}
                      min={form.fields.startsAt}
                      ariaLabel={t('claim_edit_field_ends_at', locale)}
                    />
                  </div>
                </div>

                <div className={styles.fieldCol}>
                  <div className={styles.fieldHead}>
                    <label className={styles.label} htmlFor="image_url">{t('claim_edit_field_image', locale)}</label>
                    {renderPin('image_url')}
                  </div>
                  <FileField
                    id="image_url"
                    accept={ORGANIZER_IMAGE_ACCEPT}
                    onSelect={form.uploadImage}
                    onClear={form.clearImage}
                    previewUrl={form.fields.imageUrl}
                    uploading={form.imageUploading}
                    disabled={form.isSaving || form.imageUploading}
                    chooseLabel={t('organizer_image_choose', locale)}
                    replaceLabel={t('organizer_image_replace', locale)}
                    emptyLabel={t('organizer_image_none', locale)}
                    uploadingLabel={t('organizer_image_uploading', locale)}
                    removeLabel={t('organizer_image_remove', locale)}
                  />
                  {form.imageError && <p className={styles.error} role="alert">{form.imageError}</p>}
                </div>

                <div className={styles.fieldCol}>
                  <div className={styles.fieldHead}>
                    <label className={styles.label} htmlFor="url">{t('claim_edit_field_url', locale)}</label>
                    {renderPin('url')}
                  </div>
                  <input
                    id="url"
                    type="text"
                    className={styles.input}
                    value={form.fields.url}
                    onChange={(e) => form.setField('url', 'url', e.target.value)}
                  />
                </div>
              </div>
            </div>

            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('claim_edit_field_categories', locale)}</div>
              <div className={styles.fields}>
                <CategoryPicker
                  options={categoryOpts}
                  selected={[...form.data.categories, ...form.pendingCategories]}
                  locked={form.data.categories}
                  max={ORGANIZER_MAX_CATEGORIES}
                  onToggle={form.togglePendingCategory}
                  ariaLabel={t('claim_edit_field_categories', locale)}
                  locale={locale}
                />
                <span className={styles.hint}>
                  {form.data.categories.length >= ORGANIZER_MAX_CATEGORIES
                    ? ti('claim_edit_categories_full', locale, { max: String(ORGANIZER_MAX_CATEGORIES) })
                    : ti('claim_edit_categories_hint', locale, { max: String(ORGANIZER_MAX_CATEGORIES) })}
                </span>
              </div>
            </div>

            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('claim_edit_field_price', locale)}</div>
              <div className={styles.fields}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldCol}>
                    <label className={styles.label} htmlFor="price_min">
                      {t('organizer_field_price_min', locale)} ({currencySymbol(form.fields.currency || 'EUR')})
                    </label>
                    <input
                      id="price_min"
                      type="number"
                      min={0}
                      className={styles.input}
                      value={form.fields.priceMin}
                      onChange={(e) => form.setField('priceMin', 'price_min', e.target.value)}
                    />
                  </div>
                  <div className={styles.fieldCol}>
                    <label className={styles.label} htmlFor="price_max">
                      {t('organizer_field_price_max', locale)} ({currencySymbol(form.fields.currency || 'EUR')})
                    </label>
                    <input
                      id="price_max"
                      type="number"
                      min={0}
                      className={styles.input}
                      value={form.fields.priceMax}
                      onChange={(e) => form.setField('priceMax', 'price_max', e.target.value)}
                    />
                  </div>
                  <div className={styles.fieldCol}>
                    <label className={styles.label} htmlFor="currency">{t('claim_edit_field_currency', locale)}</label>
                    <input
                      id="currency"
                      type="text"
                      className={styles.input}
                      value={form.fields.currency}
                      onChange={(e) => form.setField('currency', 'currency', e.target.value)}
                    />
                  </div>
                </div>
                <span className={styles.hint}>{t('claim_edit_price_hint', locale)}</span>

                {form.data.price_mismatch && (
                  <div className={styles.mismatch}>
                    <div>
                      <div className={styles.mismatchHeading}>{t('claim_edit_price_mismatch_heading', locale)}</div>
                      <div className={styles.mismatchBody}>{t('claim_edit_price_mismatch_body', locale)}</div>
                    </div>
                    <button
                      type="button"
                      className={styles.mismatchAccept}
                      onClick={form.acceptNewPrice}
                      disabled={form.isAcceptingPrice}
                    >
                      {t('claim_edit_price_accept', locale)}
                    </button>
                  </div>
                )}
              </div>
            </div>

            {form.saveError && <p className={styles.error} role="alert">{form.saveError}</p>}
            {form.savedStatus && (
              <p
                className={cx(
                  styles.saveStatus,
                  form.savedStatus === EVENT_STATUS.published && styles.saveStatusSuccess,
                )}
                role="status"
              >
                {form.savedStatus === EVENT_STATUS.published
                  ? t('claim_edit_save_success', locale)
                  : t('claim_edit_save_needs_fix', locale)}
              </p>
            )}

            <div className={styles.saveBar}>
              <span className={styles.saveHint}>{t('claim_edit_save_hint', locale)}</span>
              <button
                type="button"
                className={styles.save}
                onClick={form.save}
                disabled={form.isSaving}
              >
                {t('claim_edit_save', locale)}
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
