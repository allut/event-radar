import { Fragment, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { t, ti } from '../../i18n';
import { safeUrl, titleWithBrand } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useLogout } from '../../hooks/useLogout';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { LEGAL_LOADERS, type LegalDocId } from '../../content/legal';
import type { LegalBlock, LegalDoc, LegalInline } from '../../content/legal/types';
import { LOCALE_EN, MAILTO_SCHEME, SAFE_URL_SCHEMES, UI_STATE } from '../../constants';
import TopBar from '../TopBar';
import PageState from '../PageState';
import SeoTags from '../SeoTags';
import styles from './LegalPage.module.css';

// Legal content also links out via mailto: (the contact address) alongside
// ordinary https: links — both are first-party authored, not user data.
const LEGAL_LINK_SCHEMES = new Set([...SAFE_URL_SCHEMES, MAILTO_SCHEME]);

interface LegalPageProps {
  docId: LegalDocId;
  /** i18n key for the short page title (footer nav label / loading heading). */
  titleKey: string;
}

/** Fallback locale for legal chunks (matches t()'s fallback in i18n.ts). */
const FALLBACK_LOCALE = LOCALE_EN;

/** Flatten an inline run to plain text, for building stable React keys off the
 * authored content (the codebase keys lists on their content, not array index —
 * react/no-array-index-key is an error). */
function inlineText(content: LegalInline[]): string {
  return content.map((part) => (typeof part === 'string' ? part : part.text)).join('');
}

/** One inline run → text node or external link. Inline content is structured
 * data (never raw HTML), so no sanitization is needed for this first-party
 * authored prose. */
function renderInline(content: LegalInline[]): React.ReactNode[] {
  return content.map((part) => {
    if (typeof part === 'string') return <Fragment key={`t:${part}`}>{part}</Fragment>;
    const href = safeUrl(part.href, LEGAL_LINK_SCHEMES);
    if (!href) return <Fragment key={`a:${part.href}`}>{part.text}</Fragment>;
    return (
      <a key={`a:${part.href}`} className={styles.link} href={href} rel="noopener noreferrer">
        {part.text}
      </a>
    );
  });
}

function renderBlock(block: LegalBlock): React.ReactNode {
  if (block.kind === 'ul') {
    return (
      <ul key={`ul:${inlineText(block.items[0] ?? [])}`} className={styles.list}>
        {block.items.map((item) => (
          <li key={inlineText(item)}>{renderInline(item)}</li>
        ))}
      </ul>
    );
  }
  return (
    <p key={`p:${inlineText(block.content)}`} className={styles.body}>
      {renderInline(block.content)}
    </p>
  );
}

/** Structured legal-document page (Privacy, Terms). Lazy-loads the LegalDoc for
 * the active locale (falling back to the default locale), mirroring StaticPage's
 * TopBar + locale-mutation wiring but rendering rich sections instead of flat
 * paragraphs. */
export default function LegalPage({ docId, titleKey }: LegalPageProps) {
  const authed = useAuth();
  const handleLogout = useLogout();
  // No server data keyed to locale — the doc is re-loaded by the effect below —
  // so the invalidation key is an inert sentinel (matches StaticPage).
  const { locale, handleLocaleChange } = useLocaleMutation();
  const { pathname } = useLocation();
  const seoMeta = useSeoMeta({ title: titleWithBrand(t(titleKey, locale), locale), locale, path: pathname });
  // Keyed by `${docId}:${locale}` so a stale-key load renders as loading without
  // a synchronous setState(null) in the effect (react-hooks/set-state-in-effect).
  const [result, setResult] = useState<
    { key: string; doc: LegalDoc } | { key: string; error: true } | null
  >(null);
  const currentKey = `${docId}:${locale}`;

  useEffect(() => {
    let active = true;
    const loaders = LEGAL_LOADERS[docId];
    // Load the active locale's chunk, falling back to the default locale's chunk
    // if it fails. A single outer .catch() surfaces an error state when even the
    // fallback fails (e.g. a stale dynamic-import chunk hash after a deploy) —
    // otherwise the rejection is unhandled and the page spins forever.
    const loadDoc = async (): Promise<LegalDoc> => {
      try {
        return (await (loaders[locale] ?? loaders[FALLBACK_LOCALE])()).default;
      } catch (err) {
        if (locale === FALLBACK_LOCALE) throw err;
        return (await loaders[FALLBACK_LOCALE]()).default;
      }
    };
    loadDoc()
      .then((doc) => {
        if (active) setResult({ key: currentKey, doc });
      })
      .catch(() => {
        if (active) setResult({ key: currentKey, error: true });
      });
    return () => {
      active = false;
    };
  }, [docId, locale, currentKey]);

  const current = result?.key === currentKey ? result : null;
  const doc = current && 'doc' in current ? current.doc : null;
  const failed = current != null && 'error' in current;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        authed={authed}
      />

      <main className={styles.main}>
        {failed ? (
          <PageState kind={UI_STATE.error} message={t('generic_error', locale)} />
        ) : doc === null ? (
          <PageState kind={UI_STATE.loading} message={t(titleKey, locale)} />
        ) : (
          <>
            <h1 className={styles.title}>{doc.title}</h1>
            <p className={styles.lastUpdated}>
              {ti('legal_last_updated', locale, { date: doc.lastUpdated })}
            </p>
            {doc.intro.map((block) => renderBlock(block))}
            {doc.sections.map((section) => (
              <section key={section.heading} className={styles.section}>
                <h2 className={styles.h2}>{section.heading}</h2>
                {section.blocks.map((block) => renderBlock(block))}
              </section>
            ))}
          </>
        )}
      </main>
    </div>
  );
}
