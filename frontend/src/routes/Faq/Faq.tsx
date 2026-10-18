import { Fragment, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { t } from '../../i18n';
import { inlineText, safeUrl, titleWithBrand } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useLogout } from '../../hooks/useLogout';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { FAQ_LOADERS } from '../../content/faq/loaders';
import type { FaqBlock, FaqDoc, FaqInline } from '../../content/faq/types';
import { resolveSlotsGate } from '../../content/slotsGate';
import { isPromotionsSlotsEnabled } from '../../constants/sponsored';
import { SAFE_URL_SCHEMES } from '../../_generated/sharedConstants';
import { LOCALE_EN, MAILTO_SCHEME, UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { OG_FALLBACK_IMAGE_PATH, PRODUCTION_ORIGIN } from '../../constants/seo';
import { REDUCED_MOTION_QUERY } from '../../constants/theme';
import TopBar from '../../components/TopBar';
import PageState from '../../components/PageState';
import SeoTags from '../../components/SeoTags';
import styles from './Faq.module.css';

// FAQ answers link out via mailto: (the contact address) as well as https: —
// both first-party authored, not user data (same set as LegalPage).
const FAQ_LINK_SCHEMES = new Set([...SAFE_URL_SCHEMES, MAILTO_SCHEME]);

/** Fallback locale for FAQ chunks (matches t()'s fallback in i18n.ts). */
const FALLBACK_LOCALE = LOCALE_EN;

/** One inline run → text node, router link (`to`, locale-prefixed) or external
 * link (`href`). Structured first-party data, never raw HTML. */
function renderInline(content: FaqInline[], localePath: (to: string) => string): React.ReactNode[] {
  return content.map((part) => {
    if (typeof part === 'string') return <Fragment key={`t:${part}`}>{part}</Fragment>;
    if ('to' in part) {
      return (
        <Link key={`l:${part.to}:${part.text}`} className={styles.link} to={localePath(part.to)}>
          {part.text}
        </Link>
      );
    }
    const href = safeUrl(part.href, FAQ_LINK_SCHEMES);
    if (!href) return <Fragment key={`a:${part.href}`}>{part.text}</Fragment>;
    return (
      <a key={`a:${part.href}`} className={styles.link} href={href} rel="noopener noreferrer">
        {part.text}
      </a>
    );
  });
}

/** Whether `id` names one of the doc's sections or questions — the only
 * anchors a deep link may act on (never an arbitrary element id on the page). */
function isFaqAnchor(doc: FaqDoc, id: string): boolean {
  return doc.sections.some(
    (section) => section.id === id || section.items.some((item) => item.id === id),
  );
}

function renderBlock(block: FaqBlock, localePath: (to: string) => string): React.ReactNode {
  if (block.kind === 'ul') {
    // The doc is resolved before rendering, so every item is a bare inline run.
    const items = block.items as FaqInline[][];
    return (
      <ul key={`ul:${inlineText(items[0] ?? [])}`} className={styles.list}>
        {items.map((item) => (
          <li key={inlineText(item)}>{renderInline(item, localePath)}</li>
        ))}
      </ul>
    );
  }
  return (
    <p key={`p:${inlineText(block.content)}`} className={styles.answer}>
      {renderInline(block.content, localePath)}
    </p>
  );
}

/** Public FAQ page (`/faq`, a noRedirect SEO route). Lazy-loads the FaqDoc for
 * the active locale (falling back to English, then to an error state) — the
 * loader/TopBar wiring mirrors LegalPage, the layout is its own: a jump-nav
 * header, one <details> per question, and a closing contact block. Answers are
 * always in the DOM (closed <details>), so the prerendered HTML carries them. */
export default function Faq() {
  const authed = useAuth();
  const handleLogout = useLogout();
  const { locale, handleLocaleChange } = useLocaleMutation({ publicRoute: true });
  const localePath = useLocalePath();
  const { pathname, hash } = useLocation();
  // Keyed by locale so a stale-locale load renders as loading without a
  // synchronous setState(null) in the effect (react-hooks/set-state-in-effect).
  const [result, setResult] = useState<
    { key: string; doc: FaqDoc } | { key: string; error: true } | null
  >(null);

  useEffect(() => {
    let active = true;
    // Active locale's chunk, else English's; one outer .catch() surfaces an
    // error state when even the fallback fails (e.g. a stale chunk hash after
    // a deploy) instead of spinning forever.
    const own = FAQ_LOADERS[locale];
    const loadDoc = async (): Promise<FaqDoc> => {
      try {
        return resolveSlotsGate((await (own ?? FAQ_LOADERS[FALLBACK_LOCALE])()).default, isPromotionsSlotsEnabled());
      } catch (err) {
        // No own chunk means English was the one that just failed.
        if (!own || locale === FALLBACK_LOCALE) throw err;
        return resolveSlotsGate((await FAQ_LOADERS[FALLBACK_LOCALE]()).default, isPromotionsSlotsEnabled());
      }
    };
    loadDoc()
      .then((doc) => {
        if (active) setResult({ key: locale, doc });
      })
      .catch(() => {
        if (active) setResult({ key: locale, error: true });
      });
    return () => {
      active = false;
    };
  }, [locale]);

  const current = result?.key === locale ? result : null;
  const doc = current && 'doc' in current ? current.doc : null;
  const failed = current != null && 'error' in current;

  // Deep link (#slug): once the doc has rendered, and on every in-app hash
  // change, open the named question and scroll it (or a section) clear of the
  // sticky TopBar via scroll-margin-top. The browser's own hash jump can't do
  // it — createRoot replaced the prerendered DOM before the answers existed.
  // `open` is set imperatively and never rendered by React, so the summary
  // still toggles the item natively afterwards. Ids are ASCII slugs, so the
  // raw hash compares directly (no decode, nothing to throw on).
  useEffect(() => {
    if (!doc) return;
    const id = hash.slice(1);
    if (!isFaqAnchor(doc, id)) return;
    const target = document.getElementById(id);
    if (!target) return;
    if (target instanceof HTMLDetailsElement) target.open = true;
    const behavior: ScrollBehavior = window.matchMedia(REDUCED_MOTION_QUERY).matches
      ? 'auto'
      : 'smooth';
    // Next frame, so the just-opened answer has laid out before the scroll.
    const frame = requestAnimationFrame(() => target.scrollIntoView({ behavior, block: 'start' }));
    return () => cancelAnimationFrame(frame);
  }, [doc, hash]);

  // noindex until the doc has loaded, so a prerender snapshot of the loading
  // or error state can never be indexed.
  const seoMeta = useSeoMeta({
    title: titleWithBrand(doc ? doc.seoTitle : t('nav_faq', locale), locale),
    locale,
    path: pathname,
    indexable: Boolean(doc),
    description: doc?.metaDescription,
    image: `${PRODUCTION_ORIGIN}${OG_FALLBACK_IMAGE_PATH}`,
  });

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
          <PageState kind={UI_STATE.loading} message={t('nav_faq', locale)} />
        ) : (
          <>
            <header className={styles.header}>
              <h1 className={styles.title}>{doc.title}</h1>
              <p className={styles.lede}>{doc.lede}</p>
              <nav className={styles.jumpNav} aria-label={doc.jumpNavLabel}>
                {doc.sections.map((section) => (
                  <a key={section.id} className={styles.jumpLink} href={`#${section.id}`}>
                    {section.heading}
                  </a>
                ))}
              </nav>
            </header>

            {doc.sections.map((section) => (
              <section key={section.id} id={section.id} className={styles.section}>
                <h2 className={styles.sectionTitle}>{section.heading}</h2>
                <div className={styles.items}>
                  {section.items.map((item) => (
                    <details key={item.id} id={item.id} className={styles.item}>
                      <summary className={styles.question}>
                        <span>{item.question}</span>
                        <span className={styles.mark} aria-hidden="true">+</span>
                      </summary>
                      <div className={styles.body}>
                        {item.answer.map((block) => renderBlock(block, localePath))}
                        <a className={styles.answerLink} href={`#${item.id}`}>
                          {doc.answerLinkLabel}
                        </a>
                      </div>
                    </details>
                  ))}
                </div>
              </section>
            ))}

            <aside className={styles.contact}>
              <h2 className={styles.contactHeading}>{doc.contact.heading}</h2>
              <p className={styles.answer}>{doc.contact.body}</p>
              <Link className={styles.contactCta} to={localePath(ROUTES.contact)}>
                {doc.contact.cta}
              </Link>
            </aside>
          </>
        )}
      </main>
    </div>
  );
}
