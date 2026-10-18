import { Fragment, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { t, ti } from '../../i18n';
import { inlineText, safeUrl, titleWithBrand } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useLogout } from '../../hooks/useLogout';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { LEGAL_LOADERS, type LegalDocId } from '../../content/legal/loaders';
import { resolveLegalDoc } from '../../content/slotsGate';
import type { LegalBlock, LegalDoc, LegalInline } from '../../content/legal/types';
import { SAFE_URL_SCHEMES } from '../../_generated/sharedConstants';
import { LOCALE_EN, MAILTO_SCHEME, UI_STATE } from '../../constants/core';
import { OPERATOR_FIELD_LABELS, OPERATOR_IDENTITY } from '../../constants/operator';
import { isPromotionsSlotsEnabled } from '../../constants/sponsored';
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

/** One inline run → text node, router link (`to`, locale-prefixed), external
 * link (`href`) or an Operator identity field. Inline content is structured
 * data (never raw HTML), so no sanitization is needed for this first-party
 * authored prose. */
function renderInline(
  content: LegalInline[],
  locale: string,
  localePath: (to: string) => string,
): React.ReactNode[] {
  return content.map((part) => {
    if (typeof part === 'string') return <Fragment key={`t:${part}`}>{part}</Fragment>;
    if ('operator' in part) {
      const value = OPERATOR_IDENTITY[part.operator];
      if (value !== null) return <Fragment key={`o:${part.operator}`}>{value}</Fragment>;
      const label = OPERATOR_FIELD_LABELS[part.operator][locale] ?? OPERATOR_FIELD_LABELS[part.operator][FALLBACK_LOCALE];
      return (
        <mark key={`o:${part.operator}`} className={styles.placeholder} data-operator-field={part.operator}>
          {`\u27E8${label}\u27E9`}
        </mark>
      );
    }
    if ('to' in part) {
      return (
        <Link key={`l:${part.to}:${part.text}`} className={styles.link} to={localePath(part.to)}>
          {part.text}
        </Link>
      );
    }
    const href = safeUrl(part.href, LEGAL_LINK_SCHEMES);
    if (!href) return <Fragment key={`a:${part.href}`}>{part.text}</Fragment>;
    return (
      <a key={`a:${part.href}`} className={styles.link} href={href} rel="noopener noreferrer">
        {part.text}
      </a>
    );
  });
}

function renderBlock(block: LegalBlock, locale: string, localePath: (to: string) => string): React.ReactNode {
  if (block.kind === 'ul' || block.kind === 'ol') {
    const List = block.kind;
    // The doc is resolved before rendering, so every item is a bare inline run.
    const items = block.items as LegalInline[][];
    return (
      <List
        key={`${block.kind}:${inlineText(items[0] ?? [])}`}
        className={block.kind === 'ol' ? styles.orderedList : styles.list}
      >
        {items.map((item) => (
          <li key={inlineText(item)}>{renderInline(item, locale, localePath)}</li>
        ))}
      </List>
    );
  }
  return (
    <p key={`p:${inlineText(block.content)}`} className={styles.body}>
      {renderInline(block.content, locale, localePath)}
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
  const localePath = useLocalePath();
  const { pathname, hash } = useLocation();
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
        return resolveLegalDoc((await (loaders[locale] ?? loaders[FALLBACK_LOCALE])()).default, isPromotionsSlotsEnabled());
      } catch (err) {
        if (locale === FALLBACK_LOCALE) throw err;
        return resolveLegalDoc((await loaders[FALLBACK_LOCALE]()).default, isPromotionsSlotsEnabled());
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

  // createRoot replaces the prerendered DOM and the doc loads lazily, so the
  // browser's own hash jump fires before the sections exist (/ranking#relevance).
  useEffect(() => {
    if (!doc || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [doc, hash]);
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
            {doc.draft && (
              <div className={styles.draft} role="note">
                <strong>{t('legal_draft_title', locale)}</strong>
                <span>{t('legal_draft_body', locale)}</span>
              </div>
            )}
            <h1 className={styles.title}>{doc.title}</h1>
            <p className={styles.lastUpdated}>
              {ti('legal_last_updated', locale, { date: doc.lastUpdated })}
            </p>
            {doc.intro.map((block) => renderBlock(block, locale, localePath))}
            {doc.sections.map((section) => (
              <section key={section.heading} id={section.id} className={styles.section}>
                <h2 className={styles.h2}>{section.heading}</h2>
                {section.blocks.map((block) => renderBlock(block, locale, localePath))}
              </section>
            ))}
          </>
        )}
      </main>
    </div>
  );
}
