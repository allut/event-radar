import { useLocation, useParams } from 'react-router-dom';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useClaimEventEdit } from '../../hooks/useClaimEventEdit';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import DatePicker from '../../components/DatePicker';
import SelectField from '../../components/SelectField';
import { t, ti } from '../../i18n';
import { EVENT_STATUS, LOCALE_EN, LOCALE_ET, LOCALE_RU, LOCALES_BY_CODE } from '../../constants';
import { categoryOptions, cx, currencySymbol, titleWithBrand } from '../../utils';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import SeoTags from '../../components/SeoTags';
import styles from './ClaimEventEdit.module.css';

function langLabel(code: string): string {
  return LOCALES_BY_CODE.get(code)?.label ?? code.toUpperCase();
}

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
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const { pathname } = useLocation();
  const form = useClaimEventEdit(claimId, locale);
  const seoMeta = useSeoMeta({
    title: titleWithBrand(t('claim_edit_title', locale), locale),
    locale,
    path: pathname,
  });
  const categoryOpts = categoryOptions(locale);

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

        {form.isLoading && <span className={styles.spinner} aria-label={t('loading', locale)} />}

        {form.isLocked && (
          <div className={styles.locked}>
            <h2 className={styles.lockedTitle}>{t('claim_edit_locked_title', locale)}</h2>
            <p className={styles.lockedBody}>{t('claim_edit_locked_body', locale)}</p>
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

                {([LOCALE_ET, LOCALE_EN, LOCALE_RU] as const).map((code) => (
                  <div className={styles.fieldCol} key={`title_${code}`}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} htmlFor={`title_${code}`}>
                        {code === LOCALE_ET
                          ? t('claim_edit_field_title', locale)
                          : ti('organizer_field_lang_suffix', locale, {
                              field: t('claim_edit_field_title', locale),
                              lang: langLabel(code),
                            })}
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

                {([LOCALE_ET, LOCALE_EN, LOCALE_RU] as const).map((code) => (
                  <div className={styles.fieldCol} key={`description_${code}`}>
                    <div className={styles.fieldHead}>
                      <label className={styles.label} htmlFor={`description_${code}`}>
                        {code === LOCALE_ET
                          ? t('claim_edit_field_description', locale)
                          : ti('organizer_field_lang_suffix', locale, {
                              field: t('claim_edit_field_description', locale),
                              lang: langLabel(code),
                            })}
                      </label>
                      {renderPin('description', code)}
                    </div>
                    <textarea
                      id={`description_${code}`}
                      className={styles.textarea}
                      value={
                        code === LOCALE_ET
                          ? form.fields.description
                          : code === LOCALE_EN
                            ? form.fields.descriptionEn
                            : form.fields.descriptionRu
                      }
                      onChange={(e) => {
                        if (code === LOCALE_ET) form.setField('description', 'description', e.target.value);
                        else if (code === LOCALE_EN) form.setField('descriptionEn', 'description_en', e.target.value);
                        else form.setField('descriptionRu', 'description_ru', e.target.value);
                      }}
                    />
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
                  <input
                    id="image_url"
                    type="text"
                    className={styles.input}
                    value={form.fields.imageUrl}
                    onChange={(e) => form.setField('imageUrl', 'image_url', e.target.value)}
                  />
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
                <div className={styles.chips}>
                  {form.data.categories.map((slug) => (
                    <span key={slug} className={styles.chip}>{t(`category_${slug}`, locale)}</span>
                  ))}
                  {form.pendingCategory && !form.data.categories.includes(form.pendingCategory) && (
                    <span className={cx(styles.chip, styles.chipNew)}>
                      {t(`category_${form.pendingCategory}`, locale)}
                    </span>
                  )}
                </div>
                <div className={styles.fieldCol}>
                  <SelectField
                    id="add_category"
                    value={form.pendingCategory}
                    options={categoryOpts}
                    onChange={form.setPendingCategory}
                    placeholder={t('claim_edit_category_add_placeholder', locale)}
                    ariaLabel={t('claim_edit_field_categories', locale)}
                  />
                  <span className={styles.hint}>{t('claim_edit_categories_hint', locale)}</span>
                </div>
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
              <p className={styles.hint} role="status">
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
                {form.isSaving
                  ? <span className={styles.spinner} aria-label={t('claim_edit_saving', locale)} />
                  : t('claim_edit_save', locale)}
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
