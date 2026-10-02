// .js extensions required: this module is also imported (transitively) by
// functions/api/seo-audit.ts, which Cloudflare Pages runs as unbundled ESM.
import { LOCALE_EN, LOCALE_ET, LOCALE_RU } from './constants.js';
import { PERSONA_TRANSLATIONS, TRANSLATIONS } from './_generated/i18nData.js';
import { PERSONAS_EN } from './_generated/i18nData.js';

export { TRANSLATIONS };

// Built once at module load — personaName()/personaVibe() are called per persona per
// render (Onboarding renders every persona), so a linear PERSONAS_EN.find() scan on
// every call is avoidable with a one-time indexed lookup.
const PERSONAS_EN_BY_SLUG = new Map(PERSONAS_EN.map((p) => [p.slug, p]));

function _enPersona(slug: string): { name: string; vibe: string } {
  const p = PERSONAS_EN_BY_SLUG.get(slug);
  return { name: p?.name ?? slug, vibe: p?.vibe ?? '' };
}

type NonEnglishLocale = typeof LOCALE_ET | typeof LOCALE_RU;

export function personaName(slug: string, locale: string): string {
  if (locale === LOCALE_EN) return _enPersona(slug).name;
  return PERSONA_TRANSLATIONS[slug]?.[locale as NonEnglishLocale]?.name ?? _enPersona(slug).name;
}

export function personaVibe(slug: string, locale: string): string {
  if (locale === LOCALE_EN) return _enPersona(slug).vibe;
  return PERSONA_TRANSLATIONS[slug]?.[locale as NonEnglishLocale]?.vibe ?? _enPersona(slug).vibe;
}

export function t(key: string, locale: string): string {
  const loc = locale in TRANSLATIONS ? locale as keyof typeof TRANSLATIONS : LOCALE_EN;
  return (TRANSLATIONS[loc as keyof typeof TRANSLATIONS] as Record<string, string>)[key]
    ?? (TRANSLATIONS.en as Record<string, string>)[key]
    ?? key;
}

export function ti(key: string, locale: string, vars: Record<string, string>): string {
  let str = t(key, locale);
  for (const [k, v] of Object.entries(vars)) {
    str = str.replaceAll(`{${k}}`, v);
  }
  return str;
}
