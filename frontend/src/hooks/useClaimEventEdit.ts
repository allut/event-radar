import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../api/client';
import { API, QUERY_KEYS, LOCALE_EN, LOCALE_ET, LOCALE_RU } from '../constants';
import { t } from '../i18n';
import { apiErrorMessage, hasHtmlContent, toIsoOrUndefined, toLocalInput } from '../utils';

export interface ClaimEventData {
  id: number;
  slug: string;
  title: string;
  title_localized: Record<string, string> | null;
  description: string | null;
  description_localized: Record<string, string> | null;
  starts_at: string;
  ends_at: string | null;
  url: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  has_free_tier: boolean;
  categories: string[];
  pinned_fields: string[];
  price_mismatch: {
    price_min: number | null;
    price_max: number | null;
    currency: string | null;
    has_free_tier: boolean;
  } | null;
  status: string;
}

interface FormFields {
  title: string;
  titleEn: string;
  titleRu: string;
  description: string;
  descriptionEn: string;
  descriptionRu: string;
  startsAt: string;
  endsAt: string;
  url: string;
  imageUrl: string;
  priceMin: string;
  priceMax: string;
  currency: string;
  hasFreeTier: boolean;
}

const EMPTY_FIELDS: FormFields = {
  title: '', titleEn: '', titleRu: '',
  description: '', descriptionEn: '', descriptionRu: '',
  startsAt: '', endsAt: '',
  url: '', imageUrl: '',
  priceMin: '', priceMax: '', currency: '', hasFreeTier: false,
};

function fieldsFromData(data: ClaimEventData): FormFields {
  const titleLoc = data.title_localized ?? {};
  const descLoc = data.description_localized ?? {};
  return {
    title: titleLoc[LOCALE_ET] ?? data.title,
    titleEn: titleLoc[LOCALE_EN] ?? '',
    titleRu: titleLoc[LOCALE_RU] ?? '',
    description: descLoc[LOCALE_ET] ?? data.description ?? '',
    descriptionEn: descLoc[LOCALE_EN] ?? '',
    descriptionRu: descLoc[LOCALE_RU] ?? '',
    startsAt: toLocalInput(data.starts_at),
    endsAt: toLocalInput(data.ends_at),
    url: data.url ?? '',
    imageUrl: data.image_url ?? '',
    priceMin: data.price_min !== null ? String(data.price_min) : '',
    priceMax: data.price_max !== null ? String(data.price_max) : '',
    currency: data.currency ?? '',
    hasFreeTier: data.has_free_tier,
  };
}

// PatchClaimEventBody's field names (app/routers/organizer_claim_edits.py) —
// a key is only sent when present in `touched`, mirroring the backend's
// model_fields_set gate: an omitted key never pins, a present one always
// does (for the pinnable fields), regardless of whether its value actually
// changed from what's already stored.
type TouchKey =
  | 'title' | 'title_en' | 'title_ru'
  | 'description' | 'description_en' | 'description_ru'
  | 'starts_at' | 'ends_at' | 'url' | 'image_url'
  | 'price_min' | 'price_max' | 'currency' | 'has_free_tier';

export interface UseClaimEventEditResult {
  isLoading: boolean;
  loadError: string;
  isLocked: boolean;
  data: ClaimEventData | undefined;
  fields: FormFields;
  setField: <K extends keyof FormFields>(key: K, touchKey: TouchKey, value: FormFields[K]) => void;
  isPinned: (field: string, fieldLocale?: string) => boolean;
  unpin: (field: string, fieldLocale?: string) => void;
  unpinning: string | null;
  pendingCategory: string;
  setPendingCategory: (v: string) => void;
  save: () => void;
  isSaving: boolean;
  saveError: string;
  savedStatus: string | null;
  acceptNewPrice: () => void;
  isAcceptingPrice: boolean;
}

/** Load + save state for the claim-editing surface (#416) — GET/PATCH
 * /organizer/claims/{claimId}/event. A field only pins when its key is
 * actually included in the PATCH body, so `touched` tracks exactly which
 * fields this session has edited since the last load/save; untouched
 * fields are never sent, however their current value looks. */
export function useClaimEventEdit(
  claimId: number,
  locale: string,
  eventId?: number,
): UseClaimEventEditResult {
  const queryClient = useQueryClient();
  const [fields, setFields] = useState<FormFields>(EMPTY_FIELDS);
  const [touched, setTouched] = useState<Set<TouchKey>>(new Set());
  const [pendingCategory, setPendingCategory] = useState('');
  const [unpinningKey, setUnpinningKey] = useState<string | null>(null);
  const [savedStatus, setSavedStatus] = useState<string | null>(null);
  const loadedForRef = useRef<string | undefined>(undefined);
  const loadKey = `${claimId}:${eventId ?? ''}`;

  const query = useQuery({
    queryKey: [QUERY_KEYS.organizerClaimEvent, claimId, eventId],
    queryFn: () => organizerApi.get<ClaimEventData>(API.organizerClaimEvent(claimId, eventId)),
    retry: false,
  });

  useEffect(() => {
    if (!query.data || loadedForRef.current === loadKey) return;
    loadedForRef.current = loadKey;
    void Promise.resolve().then(() => {
      setFields(fieldsFromData(query.data as ClaimEventData));
      setTouched(new Set());
    });
  }, [loadKey, query.data]);

  const setField = useCallback(
    <K extends keyof FormFields>(key: K, touchKey: TouchKey, value: FormFields[K]) => {
      setFields((prev) => ({ ...prev, [key]: value }));
      setTouched((prev) => new Set(prev).add(touchKey));
    },
    [],
  );

  const pinnedFields = query.data?.pinned_fields ?? [];
  const isPinned = (field: string, fieldLocale?: string) =>
    pinnedFields.includes(fieldLocale ? `${field}:${fieldLocale}` : field);

  function applyResponse(next: ClaimEventData) {
    queryClient.setQueryData([QUERY_KEYS.organizerClaimEvent, claimId, eventId], next);
    setSavedStatus(next.status);
  }

  const unpinMutation = useMutation({
    mutationFn: (key: string) =>
      organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId), {
        unpin: [key],
        ...(eventId !== undefined && { event_id: eventId }),
      }),
    onMutate: (key) => setUnpinningKey(key),
    onSuccess: applyResponse,
    onSettled: () => setUnpinningKey(null),
  });

  const unpin = (field: string, fieldLocale?: string) => {
    unpinMutation.mutate(fieldLocale ? `${field}:${fieldLocale}` : field);
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      if (touched.has('title')) body.title = fields.title;
      if (touched.has('title_en')) body.title_en = fields.titleEn || null;
      if (touched.has('title_ru')) body.title_ru = fields.titleRu || null;
      if (touched.has('description')) body.description = hasHtmlContent(fields.description) ? fields.description : null;
      if (touched.has('description_en')) body.description_en = hasHtmlContent(fields.descriptionEn) ? fields.descriptionEn : null;
      if (touched.has('description_ru')) body.description_ru = hasHtmlContent(fields.descriptionRu) ? fields.descriptionRu : null;
      if (touched.has('starts_at')) body.starts_at = toIsoOrUndefined(fields.startsAt);
      if (touched.has('ends_at')) body.ends_at = fields.endsAt ? toIsoOrUndefined(fields.endsAt) : null;
      if (touched.has('url')) body.url = fields.url || null;
      if (touched.has('image_url')) body.image_url = fields.imageUrl || null;
      if (touched.has('price_min')) body.price_min = fields.priceMin ? Number(fields.priceMin) : null;
      if (touched.has('price_max')) body.price_max = fields.priceMax ? Number(fields.priceMax) : null;
      if (touched.has('currency')) body.currency = fields.currency || null;
      if (touched.has('has_free_tier')) body.has_free_tier = fields.hasFreeTier;
      if (pendingCategory) body.category = pendingCategory;
      if (eventId !== undefined) body.event_id = eventId;
      return organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId), body);
    },
    onSuccess: (next) => {
      applyResponse(next);
      setFields(fieldsFromData(next));
      setTouched(new Set());
      setPendingCategory('');
    },
  });

  const acceptPriceMutation = useMutation({
    mutationFn: () =>
      organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId), {
        accept_new_price: true,
        ...(eventId !== undefined && { event_id: eventId }),
      }),
    onSuccess: (next) => {
      applyResponse(next);
      setFields((prev) => ({
        ...prev,
        priceMin: next.price_min !== null ? String(next.price_min) : '',
        priceMax: next.price_max !== null ? String(next.price_max) : '',
        currency: next.currency ?? '',
        hasFreeTier: next.has_free_tier,
      }));
    },
  });

  const isLocked = query.isError && query.error instanceof ApiError && query.error.status === 409;

  return {
    isLoading: query.isLoading,
    loadError: query.isError && !isLocked ? apiErrorMessage(query.error, t('generic_error', locale)) : '',
    isLocked,
    data: query.data,
    fields,
    setField,
    isPinned,
    unpin,
    unpinning: unpinningKey,
    pendingCategory,
    setPendingCategory,
    save: () => saveMutation.mutate(),
    isSaving: saveMutation.isPending,
    saveError: saveMutation.isError ? apiErrorMessage(saveMutation.error, t('generic_error', locale)) : '',
    savedStatus,
    acceptNewPrice: () => acceptPriceMutation.mutate(),
    isAcceptingPrice: acceptPriceMutation.isPending,
  };
}

// Re-exported for the route to build per-locale field labels the same way
// EventSubmit does (ti('organizer_field_lang_suffix', ...)).
export const CLAIM_EDIT_LOCALES = [LOCALE_ET, LOCALE_EN, LOCALE_RU] as const;
export type { FormFields as ClaimEventFormFields };
