import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../api/client';
import { API, QUERY_KEYS, ORGANIZER_EVENTS_PAGE_SIZE, DEFAULT_CURRENCY, ORGANIZER_IMAGE_ALLOWED_MIME, ROUTES, LOCALE_EN, LOCALE_ET, LOCALE_RU } from '../constants';
import { t } from '../i18n';
import { toIsoOrUndefined, toLocalInput } from '../utils';
import { useLocaleNavigate } from './useLocaleNavigate';
import type { SavedVenue, VenuePickerValue } from '../components/VenuePicker';

interface OrganizerEventFull {
  id: number;
  title: string;
  description: string | null;
  important_info: string | null;
  starts_at: string;
  ends_at: string | null;
  venue_name: string | null;
  venue_address: string | null;
  venue_id: number | null;
  url: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  categories: string[];
  title_localized?: Record<string, string> | null;
  description_localized?: Record<string, string> | null;
  important_info_localized?: Record<string, string> | null;
}

interface OrganizerEventsResponse {
  events: OrganizerEventFull[];
  limit: number;
  offset: number;
}

interface SubmitResult {
  id: number;
  slug: string;
  status: string;
}

interface FormFields {
  title: string;
  titleEn: string;
  titleRu: string;
  description: string;
  descriptionEn: string;
  descriptionRu: string;
  importantInfo: string;
  importantInfoEn: string;
  importantInfoRu: string;
  startsAt: string;
  endsAt: string;
  venue: VenuePickerValue;
  url: string;
  imageUrl: string;
  priceMin: string;
  priceMax: string;
  category: string;
}

const EMPTY_VENUE: VenuePickerValue = {
  mode: 'oneoff', save: false,
  name: '', nameEn: '', nameRu: '', address: '', addressEn: '', addressRu: '',
};

const EMPTY_FIELDS: FormFields = {
  title: '', titleEn: '', titleRu: '',
  description: '', descriptionEn: '', descriptionRu: '',
  importantInfo: '', importantInfoEn: '', importantInfoRu: '',
  startsAt: '', endsAt: '',
  venue: EMPTY_VENUE,
  url: '', imageUrl: '',
  priceMin: '', priceMax: '',
  category: '',
};

function fieldsFromExisting(existing: OrganizerEventFull): FormFields {
  // Prefill from the raw *_localized maps (not the display-locale-resolved
  // `title`/`description`/`important_info`) — the ET slot must always show
  // the Estonian base text, regardless of which locale the organizer is
  // currently browsing in. Each ET slot falls back to its resolved field
  // (title/description/important_info) when the localized map has no `et`
  // entry, covering events submitted before localized maps existed.
  const titleLoc = existing.title_localized ?? {};
  const descLoc = existing.description_localized ?? {};
  const infoLoc = existing.important_info_localized ?? {};
  return {
    ...EMPTY_FIELDS,
    title: titleLoc[LOCALE_ET] ?? existing.title,
    titleEn: titleLoc[LOCALE_EN] ?? '',
    titleRu: titleLoc[LOCALE_RU] ?? '',
    description: descLoc[LOCALE_ET] ?? existing.description ?? '',
    descriptionEn: descLoc[LOCALE_EN] ?? '',
    descriptionRu: descLoc[LOCALE_RU] ?? '',
    importantInfo: infoLoc[LOCALE_ET] ?? existing.important_info ?? '',
    importantInfoEn: infoLoc[LOCALE_EN] ?? '',
    importantInfoRu: infoLoc[LOCALE_RU] ?? '',
    startsAt: toLocalInput(existing.starts_at),
    endsAt: toLocalInput(existing.ends_at),
    // Event has no localized venue_name_en/ru columns of its own (only the
    // Venue model does) — a legacy one-off's EN/RU venue text has nowhere
    // to have come from, so prefill leaves them blank.
    venue: typeof existing.venue_id === 'number'
      ? { mode: 'saved', venueId: existing.venue_id }
      : {
          mode: 'oneoff', save: false,
          name: existing.venue_name ?? '', nameEn: '', nameRu: '',
          address: existing.venue_address ?? '', addressEn: '', addressRu: '',
        },
    url: existing.url ?? '',
    imageUrl: existing.image_url ?? '',
    priceMin: existing.price_min !== null ? String(existing.price_min) : '',
    priceMax: existing.price_max !== null ? String(existing.price_max) : '',
    category: existing.categories[0] ?? '',
  };
}

export interface UseOrganizerEventFormResult {
  isEditMode: boolean;
  title: string;
  setTitle: (v: string) => void;
  titleEn: string;
  setTitleEn: (v: string) => void;
  titleRu: string;
  setTitleRu: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  descriptionEn: string;
  setDescriptionEn: (v: string) => void;
  descriptionRu: string;
  setDescriptionRu: (v: string) => void;
  importantInfo: string;
  setImportantInfo: (v: string) => void;
  importantInfoEn: string;
  setImportantInfoEn: (v: string) => void;
  importantInfoRu: string;
  setImportantInfoRu: (v: string) => void;
  startsAt: string;
  setStartsAt: (v: string) => void;
  endsAt: string;
  setEndsAt: (v: string) => void;
  venue: VenuePickerValue;
  setVenue: (v: VenuePickerValue) => void;
  url: string;
  setUrl: (v: string) => void;
  imageUrl: string;
  clearImage: () => void;
  priceMin: string;
  setPriceMin: (v: string) => void;
  priceMax: string;
  setPriceMax: (v: string) => void;
  category: string;
  setCategory: (v: string) => void;
  uploadImage: (file: File) => void;
  imageUploading: boolean;
  imageError: string;
  submit: (e: React.FormEvent) => void;
  isSubmitting: boolean;
  submitError: string;
}

/** Submission form state + mutations for both create (POST /organizer/events)
 * and edit (PATCH /organizer/events/{id}), shared by routes/EventSubmit. */
export function useOrganizerEventForm(locale: string, eventId?: number): UseOrganizerEventFormResult {
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const isEditMode = eventId !== undefined;

  // A single object (rather than one useState per field) so the edit-mode
  // prefill effect below makes exactly one setState call — multiple direct
  // setState calls in an effect body trip react-hooks/set-state-in-effect
  // (see components/LegalPage/LegalPage.tsx for the same pattern).
  const [fields, setFields] = useState<FormFields>(EMPTY_FIELDS);

  function setField<K extends keyof FormFields>(key: K, value: FormFields[K]): void {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  // Edit-mode prefill. There is no GET /organizer/events/{id} single-event
  // endpoint — the dashboard's own list is the only read path, so prefill
  // only finds the event within its first page (ORGANIZER_EVENTS_PAGE_SIZE).
  // Accepted MVP trade-off: an organizer with more submissions than that
  // retypes an edit beyond the first page from scratch.
  const { data: listData } = useQuery({
    queryKey: [QUERY_KEYS.organizerEvents, locale],
    queryFn: () =>
      organizerApi.get<OrganizerEventsResponse>(`${API.organizerEvents}?limit=${ORGANIZER_EVENTS_PAGE_SIZE}`),
    enabled: isEditMode,
  });

  // Tracks which eventId the form is currently prefilled for (not just
  // whether *a* prefill has happened) — App.tsx renders the same <EventSubmit/>
  // element for every /organizer/events/:id/edit URL, so React Router does not
  // remount the component when navigating directly between two edit targets
  // (e.g. via browser back/forward). Comparing against eventId, rather than a
  // plain boolean flag, re-triggers the prefill instead of leaving the
  // previous event's data on screen while pointed at a new id.
  const prefilledForRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!isEditMode || !listData || prefilledForRef.current === eventId) return;
    const existing = listData.events.find((e) => e.id === eventId);
    if (!existing) return;
    prefilledForRef.current = eventId;
    // Deferred to a microtask (mirrors LegalPage.tsx's async .then() setState) —
    // react-hooks/set-state-in-effect flags a *synchronous* setState call in an
    // effect body; this is a genuine one-time hydration from a query result,
    // not a derivable-from-render value, so deferring is the correct escape
    // hatch rather than restructuring away the effect.
    void Promise.resolve().then(() => setFields(fieldsFromExisting(existing)));
  }, [eventId, isEditMode, listData]);

  const imageMutation = useMutation({
    mutationFn: (file: File) => {
      // Client-side MIME check purely to skip a doomed network round trip —
      // the server re-validates and is the real security boundary (415 on
      // mismatch), same as the <input accept> hint this mirrors.
      if (!ORGANIZER_IMAGE_ALLOWED_MIME.includes(file.type)) {
        return Promise.reject(new Error(t('generic_error', locale)));
      }
      const form = new FormData();
      form.append('file', file);
      return organizerApi.post<{ url: string }>(API.organizerEventImage, form);
    },
    onSuccess: (data) => setField('imageUrl', data.url),
  });

  const createVenueMutation = useMutation({
    mutationFn: (v: VenuePickerValue & { mode: 'oneoff' }) =>
      organizerApi.post<SavedVenue>(API.organizerVenues, {
        name: v.name.trim(),
        name_en: v.nameEn.trim() || undefined,
        name_ru: v.nameRu.trim() || undefined,
        address: v.address.trim() || undefined,
        address_en: v.addressEn.trim() || undefined,
        address_ru: v.addressRu.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerVenues] });
    },
  });

  /** Resolves the picker's in-progress state into the venue_id/venue_name
   * fields the submission API accepts — a saved pick sends venue_id as-is;
   * a one-off with "save this venue" checked creates the Venue row first
   * (#178: creation happens atomically with event submission, not before)
   * and sends the new venue_id; an unsaved one-off sends the legacy
   * free-typed venue_name/venue_address (base locale only — Event has no
   * localized venue columns), unchanged from today. */
  async function resolveVenue(): Promise<Record<string, unknown>> {
    const v = fields.venue;
    if (v.mode === 'saved') return { venue_id: v.venueId };
    if (v.save && v.name.trim()) {
      const created = await createVenueMutation.mutateAsync(v);
      // Retrying a failed submit (e.g. the event POST/PATCH that follows
      // fails) must not re-create a second Venue row — switch the form to
      // the now-saved venue so a second submit attempt reuses its id.
      setField('venue', { mode: 'saved', venueId: created.id });
      return { venue_id: created.id };
    }
    const body: Record<string, unknown> = {};
    if (v.name.trim()) body.venue_name = v.name.trim();
    if (v.address.trim()) body.venue_address = v.address.trim();
    // In edit mode, an event previously linked to a saved venue (venue_id
    // set server-side) must be explicitly unlinked when the organizer
    // switches to a one-off — the PATCH handler only clears venue_id when
    // the key is present in the request at all (organizer_events.py's
    // fields_set check), so omitting it here would silently leave the old
    // link in place even though the picker now shows a blank one-off.
    if (isEditMode) body.venue_id = null;
    return body;
  }

  function buildBody(venueFields: Record<string, unknown>): Record<string, unknown> {
    const f = fields;
    const body: Record<string, unknown> = { title: f.title.trim(), ...venueFields };
    if (f.titleEn.trim()) body.title_en = f.titleEn.trim();
    if (f.titleRu.trim()) body.title_ru = f.titleRu.trim();
    if (f.description.trim()) body.description = f.description.trim();
    if (f.descriptionEn.trim()) body.description_en = f.descriptionEn.trim();
    if (f.descriptionRu.trim()) body.description_ru = f.descriptionRu.trim();
    if (f.importantInfo.trim()) body.important_info = f.importantInfo.trim();
    if (f.importantInfoEn.trim()) body.important_info_en = f.importantInfoEn.trim();
    if (f.importantInfoRu.trim()) body.important_info_ru = f.importantInfoRu.trim();
    const startsIso = toIsoOrUndefined(f.startsAt);
    if (startsIso) body.starts_at = startsIso;
    const endsIso = toIsoOrUndefined(f.endsAt);
    if (endsIso) body.ends_at = endsIso;
    if (f.url.trim()) body.url = f.url.trim();
    // In edit mode, always send image_url (even '') so a Remove-image save can
    // clear the stored value — the PATCH handler gates the update on the key's
    // *presence* (fields_set), not its truthiness, so omitting it here (as a
    // plain truthy check would) leaves the previous image silently in place.
    if (isEditMode) {
      body.image_url = f.imageUrl.trim();
    } else if (f.imageUrl.trim()) {
      body.image_url = f.imageUrl.trim();
    }
    if (f.priceMin.trim()) body.price_min = Number(f.priceMin);
    if (f.priceMax.trim()) body.price_max = Number(f.priceMax);
    if (f.priceMin.trim() || f.priceMax.trim()) body.currency = DEFAULT_CURRENCY;
    if (f.category) body.category = f.category;
    return body;
  }

  const submitMutation = useMutation({
    mutationFn: async () => {
      const venueFields = await resolveVenue();
      const body = buildBody(venueFields);
      return isEditMode
        ? organizerApi.patch<SubmitResult>(API.organizerEvent(eventId as number), body)
        : organizerApi.post<SubmitResult>(API.organizerEvents, body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      navigate(ROUTES.organizerDashboard, { replace: true });
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!fields.title.trim() || !fields.startsAt) return;
    submitMutation.mutate();
  }

  function errorText(err: unknown): string {
    return err instanceof ApiError ? err.message : t('generic_error', locale);
  }

  return {
    isEditMode,
    title: fields.title, setTitle: (v: string) => setField('title', v),
    titleEn: fields.titleEn, setTitleEn: (v: string) => setField('titleEn', v),
    titleRu: fields.titleRu, setTitleRu: (v: string) => setField('titleRu', v),
    description: fields.description, setDescription: (v: string) => setField('description', v),
    descriptionEn: fields.descriptionEn, setDescriptionEn: (v: string) => setField('descriptionEn', v),
    descriptionRu: fields.descriptionRu, setDescriptionRu: (v: string) => setField('descriptionRu', v),
    importantInfo: fields.importantInfo, setImportantInfo: (v: string) => setField('importantInfo', v),
    importantInfoEn: fields.importantInfoEn, setImportantInfoEn: (v: string) => setField('importantInfoEn', v),
    importantInfoRu: fields.importantInfoRu, setImportantInfoRu: (v: string) => setField('importantInfoRu', v),
    startsAt: fields.startsAt, setStartsAt: (v: string) => setField('startsAt', v),
    endsAt: fields.endsAt, setEndsAt: (v: string) => setField('endsAt', v),
    venue: fields.venue, setVenue: (v: VenuePickerValue) => setField('venue', v),
    url: fields.url, setUrl: (v: string) => setField('url', v),
    imageUrl: fields.imageUrl,
    clearImage: () => { setField('imageUrl', ''); imageMutation.reset(); },
    priceMin: fields.priceMin, setPriceMin: (v: string) => setField('priceMin', v),
    priceMax: fields.priceMax, setPriceMax: (v: string) => setField('priceMax', v),
    category: fields.category, setCategory: (v: string) => setField('category', v),
    uploadImage: imageMutation.mutate,
    imageUploading: imageMutation.isPending,
    imageError: imageMutation.isError ? errorText(imageMutation.error) : '',
    submit,
    isSubmitting: submitMutation.isPending,
    submitError: submitMutation.isError ? errorText(submitMutation.error) : '',
  };
}
