import { CATEGORIES, VIBES, LOCALES, LOCALE_EN, LOCALE_RU } from '../_generated/sharedConstants';
import { LOCALES_BY_CODE, LOCALE_ET, type LocaleCode } from '../constants/core';
import { t, ti } from '../i18n';

/** Display label for a locale/content-language code, falling back to the upper-cased code. */
export function localeLabel(code: string): string {
  return LOCALES_BY_CODE.get(code)?.label ?? code.toUpperCase();
}

/** "Field (LANG)" label for a translated form field. */
export function localizedFieldLabel(key: string, locale: string, lang: string): string {
  return ti('organizer_field_lang_suffix', locale, { field: t(key, locale), lang: localeLabel(lang) });
}

/** Title + description, one slot per content language — the shape shared by the
 * organizer-submit and claim-edit form states. */
export interface LocalizedTextFields {
  title: string;
  titleEn: string;
  titleRu: string;
  description: string;
  descriptionEn: string;
  descriptionRu: string;
}

/** Splits a `*_localized` record into its [et, en, ru] slots. The ET slot falls
 * back to `base` (the display-locale-resolved field) for events that predate
 * localized maps; EN/RU are blank when absent. */
export function localizedTriplet(
  record: Record<string, string> | null | undefined,
  base: string | null | undefined,
): [string, string, string] {
  const loc = record ?? {};
  return [loc[LOCALE_ET] ?? base ?? '', loc[LOCALE_EN] ?? '', loc[LOCALE_RU] ?? ''];
}

export function isValidLocale(code: string | undefined): code is LocaleCode {
  return !!code && LOCALES.some((l) => l.code === code);
}

/** `<page title> | <brand>`, the `<title>`/SEO-meta convention every route uses. */
export function titleWithBrand(pageTitle: string, locale: string): string {
  return `${pageTitle} | ${t('brand', locale)}`;
}

/** { value, label } options for every CATEGORIES slug, localized — callers
 * still wrap the call in their own useMemo(() => categoryOptions(locale),
 * [locale]) to avoid rebuilding the 14-option list (+14 t() lookups) on
 * every render. */
export function categoryOptions(locale: string): { value: string; label: string }[] {
  return CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) }));
}

/** Same shape as categoryOptions, for VIBES. */
export function vibeOptions(locale: string): { value: string; label: string }[] {
  return VIBES.map((slug) => ({ value: slug, label: t(`vibe_${slug}`, locale) }));
}
