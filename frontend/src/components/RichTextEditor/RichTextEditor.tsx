import { useEffect, useRef, useState } from 'react';
import { EditorContent, useEditor, useEditorState } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { RICH_TEXT_HEADING_LEVELS } from '../../constants';
import { t } from '../../i18n';
import { safeUrl } from '../../utils';
import { BoldIcon, ItalicIcon, UnderlineIcon, BulletListIcon, NumberedListIcon, LinkIcon, QuoteIcon } from './icons';
import styles from './RichTextEditor.module.css';

const MARKS = [
  { key: 'bold', Icon: BoldIcon, labelKey: 'organizer_rte_bold' },
  { key: 'italic', Icon: ItalicIcon, labelKey: 'organizer_rte_italic' },
  { key: 'underline', Icon: UnderlineIcon, labelKey: 'organizer_rte_underline' },
] as const;

const HEADINGS = RICH_TEXT_HEADING_LEVELS.map((level) => ({ level, label: `H${level}` }));

const LISTS = [
  { key: 'bulletList', Icon: BulletListIcon, labelKey: 'organizer_rte_bullet_list' },
  { key: 'orderedList', Icon: NumberedListIcon, labelKey: 'organizer_rte_numbered_list' },
  { key: 'blockquote', Icon: QuoteIcon, labelKey: 'organizer_rte_blockquote' },
] as const;

export interface RichTextEditorProps {
  id?: string;
  /** Controlled HTML content. Only pushed into the editor when it differs
   * from the editor's own serialized output, so typing doesn't fight the
   * prop on every keystroke. */
  value: string;
  onChange: (html: string) => void;
  disabled?: boolean;
  'aria-labelledby'?: string;
  locale: string;
}

/** Standalone rich-text field for organizer Description/Important-info
 * fields (issue #268). Formatting set: bold/italic/underline, H3/H4,
 * bullet/numbered lists, blockquote, link — everything else is excluded
 * from the Tiptap schema itself (not just hidden from the toolbar), so
 * it's unreachable via shortcut, markdown input rule, or paste. */
export default function RichTextEditor({
  id,
  value,
  onChange,
  disabled,
  'aria-labelledby': ariaLabelledBy,
  locale,
}: RichTextEditorProps) {
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState('');
  // Caches the HTML this component itself last emitted via onChange, so the
  // value-sync effect below can compare against it instead of calling
  // editor.getHTML() a second time on every keystroke (Big-O audit M12).
  const lastEmittedHtml = useRef(value);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        strike: false,
        code: false,
        codeBlock: false,
        horizontalRule: false,
        heading: { levels: [...RICH_TEXT_HEADING_LEVELS] },
      }),
    ],
    content: value,
    editable: !disabled,
    editorProps: {
      attributes: {
        class: styles.content,
        ...(id ? { id } : {}),
        ...(ariaLabelledBy ? { 'aria-labelledby': ariaLabelledBy } : {}),
      },
    },
    onUpdate: ({ editor: e }) => {
      const html = e.getHTML();
      lastEmittedHtml.current = html;
      onChange(html);
    },
  });

  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    editor.setEditable(!disabled, false);
  }, [editor, disabled]);

  useEffect(() => {
    // isDestroyed guards a real race, not just a test artifact: the editor
    // can be torn down (e.g. a submit-triggered navigation unmounting this
    // field) between this effect being scheduled and it actually running —
    // calling getHTML()/setContent() on a destroyed editor throws (its
    // ProseMirror schema is nulled out by destroy()).
    if (!editor || editor.isDestroyed) return;
    if (value !== lastEmittedHtml.current) {
      editor.commands.setContent(value, { emitUpdate: false });
      lastEmittedHtml.current = value;
    }
  }, [editor, value]);

  const state = useEditorState({
    editor,
    selector: (ctx) => {
      if (!ctx.editor) return null;
      return {
        bold: ctx.editor.isActive('bold'),
        italic: ctx.editor.isActive('italic'),
        underline: ctx.editor.isActive('underline'),
        h3: ctx.editor.isActive('heading', { level: 3 }),
        h4: ctx.editor.isActive('heading', { level: 4 }),
        bulletList: ctx.editor.isActive('bulletList'),
        orderedList: ctx.editor.isActive('orderedList'),
        blockquote: ctx.editor.isActive('blockquote'),
        link: ctx.editor.isActive('link'),
      };
    },
  });

  if (!editor || !state) return null;

  const runMark = (key: (typeof MARKS)[number]['key']) => {
    const chain = editor.chain().focus();
    if (key === 'bold') chain.toggleBold();
    else if (key === 'italic') chain.toggleItalic();
    else chain.toggleUnderline();
    chain.run();
  };

  const runList = (key: (typeof LISTS)[number]['key']) => {
    const chain = editor.chain().focus();
    if (key === 'bulletList') chain.toggleBulletList();
    else if (key === 'orderedList') chain.toggleOrderedList();
    else chain.toggleBlockquote();
    chain.run();
  };

  const toggleHeading = (level: 3 | 4) => {
    editor.chain().focus().toggleHeading({ level }).run();
  };

  const openLink = () => {
    setLinkUrl(editor.getAttributes('link').href ?? '');
    setLinkOpen((v) => !v);
  };

  const insertLink = () => {
    const url = linkUrl.trim();
    // safeUrl() enforces the same http(s)-only scheme allowlist every other
    // untrusted URL in the app is rendered through (OWASP audit G-13) — both
    // the backend's stored-HTML sanitizer and DOMPurify at render already
    // strip a disallowed scheme, so this is immediate authoring feedback
    // rather than a new guard: a rejected URL is treated the same as an
    // empty one instead of appearing to save, then silently vanishing later.
    if (!url || !safeUrl(url)) {
      editor.chain().focus().extendMarkRange('link').unsetLink().run();
    } else {
      editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
    }
    setLinkOpen(false);
    setLinkUrl('');
  };

  const cancelLink = () => {
    setLinkOpen(false);
    setLinkUrl('');
  };

  return (
    <div className={styles.wrap} data-disabled={disabled || undefined}>
      <div className={styles.toolbar} role="toolbar" aria-label={t('organizer_rte_toolbar_label', locale)}>
        <div className={styles.group}>
          {MARKS.map(({ key, Icon, labelKey }) => (
            <button
              key={key}
              type="button"
              className={styles.btn}
              data-active={state[key] || undefined}
              aria-label={t(labelKey, locale)}
              aria-pressed={state[key]}
              onClick={() => runMark(key)}
              disabled={disabled}
            >
              <Icon />
            </button>
          ))}
        </div>
        <span className={styles.divider} aria-hidden />
        <div className={styles.group}>
          {HEADINGS.map(({ level, label }) => (
            <button
              key={level}
              type="button"
              className={styles.btnText}
              data-active={state[`h${level}` as 'h3' | 'h4'] || undefined}
              aria-label={label}
              aria-pressed={state[`h${level}` as 'h3' | 'h4']}
              onClick={() => toggleHeading(level)}
              disabled={disabled}
            >
              {label}
            </button>
          ))}
        </div>
        <span className={styles.divider} aria-hidden />
        <div className={styles.group}>
          {LISTS.map(({ key, Icon, labelKey }) => (
            <button
              key={key}
              type="button"
              className={styles.btn}
              data-active={state[key] || undefined}
              aria-label={t(labelKey, locale)}
              aria-pressed={state[key]}
              onClick={() => runList(key)}
              disabled={disabled}
            >
              <Icon />
            </button>
          ))}
        </div>
        <span className={styles.divider} aria-hidden />
        <button
          type="button"
          className={styles.btn}
          data-active={(linkOpen || state.link) || undefined}
          aria-label={t('organizer_rte_insert_link', locale)}
          aria-pressed={linkOpen || state.link}
          onClick={openLink}
          disabled={disabled}
        >
          <LinkIcon />
        </button>
      </div>
      {linkOpen && (
        <div className={styles.linkRow}>
          <input
            type="url"
            className={styles.linkInput}
            placeholder={t('organizer_rte_link_placeholder', locale)}
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            autoFocus
          />
          <button type="button" className={styles.linkInsert} onClick={insertLink}>
            {t('organizer_rte_link_insert', locale)}
          </button>
          <button type="button" className={styles.linkCancel} onClick={cancelLink}>
            {t('organizer_rte_link_cancel', locale)}
          </button>
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
}
