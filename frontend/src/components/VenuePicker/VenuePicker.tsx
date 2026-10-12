import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { LOCALE_EN, LOCALE_RU, type ContentLang } from '../../constants/core';
import {
  ORGANIZER_VENUE_NAME_MAX_LEN,
  ORGANIZER_VENUE_ADDRESS_MAX_LEN,
} from '../../constants/organizer';
import { t, ti } from '../../i18n';
import { apiErrorMessage, cx, localizedFieldLabel } from '../../utils';
import styles from './VenuePicker.module.css';

export interface SavedVenue {
  id: number;
  name: string;
  name_en: string | null;
  name_ru: string | null;
  address: string | null;
}

/** Per-locale name text — mirrors the Venue model's name/name_en/name_ru
 * columns (#174), same three-locale shape as an event's title/description/
 * important_info. address is a single non-localized field — street names
 * don't translate across locales. */
export interface VenueOneOffFields {
  name: string;
  nameEn: string;
  nameRu: string;
  address: string;
}

export type VenuePickerValue =
  | { mode: 'saved'; venueId: number }
  | ({ mode: 'oneoff'; save: boolean } & VenueOneOffFields);

interface VenuePickerProps {
  id: string;
  value: VenuePickerValue;
  onChange: (value: VenuePickerValue) => void;
  locale: string;
  /** Which language's name/address to show — the same tab that already
   * drives the submission form's title/description/important_info fields,
   * so venue text follows the one "which language am I editing" control
   * instead of a second, separate set of language tabs. */
  contentLang: ContentLang;
  disabled?: boolean;
}

function fieldLabel(key: string, locale: string, contentLang: ContentLang): string {
  const base = t(key, locale);
  return contentLang === LOCALE_EN || contentLang === LOCALE_RU
    ? localizedFieldLabel(key, locale, contentLang)
    : base;
}

type VenueTextField = 'name' | 'address';

// address has no per-locale column (street names don't translate) — only
// name routes through the content-language tab.
function keyFor(field: VenueTextField, lang: ContentLang): keyof VenueOneOffFields {
  if (field === 'address') return 'address';
  if (lang === LOCALE_EN) return 'nameEn';
  if (lang === LOCALE_RU) return 'nameRu';
  return 'name';
}

function fieldFor(fields: VenueOneOffFields, field: VenueTextField, lang: ContentLang): string {
  return fields[keyFor(field, lang)];
}

// Generic over T (rather than fixed to VenueOneOffFields) so the return type
// preserves whatever extra properties the caller's object carries — the
// one-off VenuePickerValue variant adds `mode`/`save` on top of the shared
// per-locale shape, and losing those on return would break onChange's type.
function withFieldFor<T extends VenueOneOffFields>(fields: T, field: VenueTextField, lang: ContentLang, v: string): T {
  return { ...fields, [keyFor(field, lang)]: v };
}

/** Inline searchable combobox over the organizer's saved venues (#178,
 * Variant A of the #171 prototype — no separate venue-management page,
 * everything happens here). Self-contained: owns the saved-venues list
 * query and the inline "Edit venue" PATCH, since both are internal to this
 * control's own UI action, not something the submission form needs to
 * orchestrate. The final pick/one-off/save-checkbox state is lifted to the
 * caller via value/onChange since event submission has to read it. */
export default function VenuePicker({ id, value, onChange, locale, contentLang, disabled = false }: VenuePickerProps) {
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState<VenueOneOffFields>({
    name: '', nameEn: '', nameRu: '', address: '',
  });

  const { data: venues = [] } = useQuery({
    queryKey: [QUERY_KEYS.organizerVenues],
    queryFn: () => organizerApi.get<SavedVenue[]>(API.organizerVenues),
  });

  const selectedVenueId = value.mode === 'saved' ? value.venueId : undefined;
  const selected = useMemo(
    () => (selectedVenueId !== undefined ? venues.find((v) => v.id === selectedVenueId) : undefined),
    [venues, selectedVenueId],
  );

  // Deferred to a microtask (mirrors useOrganizerEventForm.ts's prefill
  // effect / OrganizerSettings.tsx's hydration) — this is a one-time draft
  // hydration when the edit form opens, not a value derivable from render,
  // so react-hooks/set-state-in-effect's synchronous-setState flag doesn't
  // apply once deferred.
  //
  // Keyed on the venue's id, not the `selected` object: a background refetch of
  // the venues query hands back a new object identity for the same venue, and
  // re-hydrating on that would clobber in-progress edits. The latest row is
  // read through a ref so the effect still hydrates from current data.
  const selectedRef = useRef(selected);
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const hasSelected = selected !== undefined;
  useEffect(() => {
    const venue = selectedRef.current;
    if (editOpen && hasSelected && venue) {
      void Promise.resolve().then(() => {
        setDraft({
          name: venue.name,
          nameEn: venue.name_en ?? '',
          nameRu: venue.name_ru ?? '',
          address: venue.address ?? '',
        });
      });
    }
  }, [editOpen, selectedVenueId, hasSelected]);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const updateMutation = useMutation({
    mutationFn: () =>
      organizerApi.patch<SavedVenue>(API.organizerVenue((selected as SavedVenue).id), {
        name: draft.name.trim(),
        name_en: draft.nameEn.trim() || null,
        name_ru: draft.nameRu.trim() || null,
        address: draft.address.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerVenues] });
      setEditOpen(false);
    },
  });

  const matches = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return venues.filter((v) => v.name.toLowerCase().includes(normalizedQuery));
  }, [venues, query]);

  function selectSaved(venue: SavedVenue) {
    onChange({ mode: 'saved', venueId: venue.id });
    setQuery('');
    setOpen(false);
    setEditOpen(false);
  }

  function selectOneOff() {
    onChange({
      mode: 'oneoff', save: false,
      name: query.trim(), nameEn: '', nameRu: '', address: '',
    });
    setQuery('');
    setOpen(false);
  }

  const listId = `${id}-listbox`;

  return (
    <div className={styles.wrap}>
      <label className={styles.label} htmlFor={id}>{t('organizer_field_venue', locale)}</label>
      <div className={styles.box} ref={rootRef}>
        <input
          id={id}
          type="text"
          className={styles.input}
          value={query}
          placeholder={value.mode === 'saved' && selected ? selected.name : t('organizer_venue_search_placeholder', locale)}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          disabled={disabled}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
        />
        {open && !disabled && (
          <div className={styles.pop} id={listId} role="listbox" aria-label={t('organizer_field_venue', locale)}>
            {matches.map((v) => (
              <button
                key={v.id}
                type="button"
                role="option"
                aria-selected={value.mode === 'saved' && value.venueId === v.id}
                className={styles.option}
                onClick={() => selectSaved(v)}
              >
                <span className={styles.optionName}>{v.name}</span>
                {v.address && <span className={styles.optionAddress}>{v.address}</span>}
              </button>
            ))}
            <button type="button" className={styles.oneOffOption} onClick={selectOneOff}>
              {query.trim()
                ? ti('organizer_venue_oneoff_option', locale, { query: query.trim() })
                : t('organizer_venue_oneoff_option_empty', locale)}
            </button>
          </div>
        )}
      </div>

      {value.mode === 'saved' && selected && !editOpen && (
        <div className={styles.selectedRow}>
          {selected.address && <span className={styles.selectedAddress}>{selected.address}</span>}
          <button type="button" className={styles.editToggle} onClick={() => setEditOpen(true)} disabled={disabled}>
            {t('organizer_venue_edit_toggle', locale)}
          </button>
        </div>
      )}

      {value.mode === 'saved' && selected && editOpen && (
        <div className={styles.miniForm}>
          <input
            type="text"
            className={styles.miniInput}
            value={fieldFor(draft, 'name', contentLang)}
            onChange={(e) => setDraft((d) => withFieldFor(d, 'name', contentLang, e.target.value))}
            placeholder={fieldLabel('organizer_field_venue_name', locale, contentLang)}
            disabled={disabled}
            maxLength={ORGANIZER_VENUE_NAME_MAX_LEN}
          />
          <input
            type="text"
            className={styles.miniInput}
            value={fieldFor(draft, 'address', contentLang)}
            onChange={(e) => setDraft((d) => withFieldFor(d, 'address', contentLang, e.target.value))}
            placeholder={t('organizer_field_venue_address', locale)}
            disabled={disabled}
            maxLength={ORGANIZER_VENUE_ADDRESS_MAX_LEN}
          />
          <div className={styles.miniFormActions}>
            <button
              type="button"
              className={styles.saveBtn}
              disabled={disabled || updateMutation.isPending || !draft.name.trim()}
              onClick={() => updateMutation.mutate()}
            >
              {t('organizer_venue_edit_save', locale)}
            </button>
            <button type="button" className={styles.editToggle} onClick={() => setEditOpen(false)} disabled={disabled}>
              {t('organizer_venue_edit_done', locale)}
            </button>
          </div>
          {updateMutation.isError && (
            <p className={styles.error} role="alert">
              {apiErrorMessage(updateMutation.error, t('generic_error', locale))}
            </p>
          )}
          <p className={styles.hint}>{t('organizer_venue_edit_hint', locale)}</p>
        </div>
      )}

      {value.mode === 'oneoff' && (
        <div className={cx(styles.miniForm, styles.oneOffForm)}>
          <input
            type="text"
            className={styles.miniInput}
            value={fieldFor(value, 'name', contentLang)}
            onChange={(e) => onChange(withFieldFor(value, 'name', contentLang, e.target.value))}
            placeholder={fieldLabel('organizer_field_venue_name', locale, contentLang)}
            disabled={disabled}
            maxLength={ORGANIZER_VENUE_NAME_MAX_LEN}
          />
          <input
            type="text"
            className={styles.miniInput}
            value={fieldFor(value, 'address', contentLang)}
            onChange={(e) => onChange(withFieldFor(value, 'address', contentLang, e.target.value))}
            placeholder={t('organizer_field_venue_address', locale)}
            disabled={disabled}
            maxLength={ORGANIZER_VENUE_ADDRESS_MAX_LEN}
          />
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={value.save}
              onChange={(e) => onChange({ ...value, save: e.target.checked })}
              disabled={disabled}
            />
            {t('organizer_venue_save_checkbox', locale)}
          </label>
          {value.save && (
            <p className={styles.hint}>{t('organizer_venue_oneoff_locale_hint', locale)}</p>
          )}
        </div>
      )}
    </div>
  );
}
