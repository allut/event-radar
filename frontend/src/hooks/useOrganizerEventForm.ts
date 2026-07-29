import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizerApi, ApiError } from '../api/client';
import { QUERY_KEYS, ORGANIZER_EVENTS_PAGE_SIZE, DEFAULT_CURRENCY, ORGANIZER_IMAGE_ALLOWED_MIME } from '../constants';
import { t } from '../i18n';

interface OrganizerEventFull {
  id: number;
  title: string;
  description: string | null;
  important_info: string | null;
  starts_at: string;
  ends_at: string | null;
  venue_name: string | null;
  venue_address: string | null;
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
  venueName: string;
  venueAddress: string;
  url: string;
  imageUrl: string;
  priceMin: string;
  priceMax: string;
  category: string;
}

const EMPTY_FIELDS: FormFields = {
  title: '', titleEn: '', titleRu: '',
  description: '', descriptionEn: '', descriptionRu: '',
  importantInfo: '', importantInfoEn: '', importantInfoRu: '',
  startsAt: '', endsAt: '',
  venueName: '', venueAddress: '',
  url: '', imageUrl: '',
  priceMin: '', priceMax: '',
  category: '',
};

function toIsoOrUndefined(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

// datetime-local has no timezone of its own — the browser's local offset is
// used both when parsing (toIsoOrUndefined) and here, so round-tripping an
// existing ISO value back into the input reproduces the same wall-clock time
// the organizer originally entered.
function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

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
    title: titleLoc.et ?? existing.title,
    titleEn: titleLoc.en ?? '',
    titleRu: titleLoc.ru ?? '',
    description: descLoc.et ?? existing.description ?? '',
    descriptionEn: descLoc.en ?? '',
    descriptionRu: descLoc.ru ?? '',
    importantInfo: infoLoc.et ?? existing.important_info ?? '',
    importantInfoEn: infoLoc.en ?? '',
    importantInfoRu: infoLoc.ru ?? '',
    startsAt: toLocalInput(existing.starts_at),
    endsAt: toLocalInput(existing.ends_at),
    venueName: existing.venue_name ?? '',
    venueAddress: existing.venue_address ?? '',
    url: existing.url ?? '',
    imageUrl: existing.image_url ?? '',
    priceMin: existing.price_min !== null ? String(existing.price_min) : '',
    priceMax: existing.price_max !== null ? String(existing.price_max) : '',
    category: existing.categories[0] ?? '',
  };
}

/** Submission form state + mutations for both create (POST /organizer/events)
 * and edit (PATCH /organizer/events/{id}), shared by routes/EventSubmit. */
export function useOrganizerEventForm(locale: string, eventId?: number) {
  const navigate = useNavigate();
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
      organizerApi.get<OrganizerEventsResponse>(`/organizer/events?limit=${ORGANIZER_EVENTS_PAGE_SIZE}`),
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
      return organizerApi.post<{ url: string }>('/organizer/events/image', form);
    },
    onSuccess: (data) => setField('imageUrl', data.url),
  });

  function buildBody(): Record<string, unknown> {
    const f = fields;
    const body: Record<string, unknown> = { title: f.title.trim() };
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
    if (f.venueName.trim()) body.venue_name = f.venueName.trim();
    if (f.venueAddress.trim()) body.venue_address = f.venueAddress.trim();
    if (f.url.trim()) body.url = f.url.trim();
    if (f.imageUrl.trim()) body.image_url = f.imageUrl.trim();
    if (f.priceMin.trim()) body.price_min = Number(f.priceMin);
    if (f.priceMax.trim()) body.price_max = Number(f.priceMax);
    if (f.priceMin.trim() || f.priceMax.trim()) body.currency = DEFAULT_CURRENCY;
    if (f.category) body.category = f.category;
    return body;
  }

  const submitMutation = useMutation({
    mutationFn: () =>
      isEditMode
        ? organizerApi.patch<SubmitResult>(`/organizer/events/${eventId}`, buildBody())
        : organizerApi.post<SubmitResult>('/organizer/events', buildBody()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      navigate('/organizer/dashboard', { replace: true });
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
    venueName: fields.venueName, setVenueName: (v: string) => setField('venueName', v),
    venueAddress: fields.venueAddress, setVenueAddress: (v: string) => setField('venueAddress', v),
    url: fields.url, setUrl: (v: string) => setField('url', v),
    imageUrl: fields.imageUrl,
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
