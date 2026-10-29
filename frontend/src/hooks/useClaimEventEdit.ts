import { StatusCodes } from 'http-status-codes';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../api/client';
import { ORGANIZER_MAX_CATEGORIES } from '../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../constants/api';
import { CLAIM_ERROR_CODE_DORMANT } from '../constants/claims';
import { t } from '../i18n';
import { useOrganizerImageUpload } from './useOrganizerImageUpload';
import { apiErrorMessage, hasHtmlContent, localizedTriplet, toIsoOrUndefined, toLocalInput, toggleCapped, type LocalizedTextFields } from '../utils';

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

interface FormFields extends LocalizedTextFields {
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
  const [title, titleEn, titleRu] = localizedTriplet(data.title_localized, data.title);
  const [description, descriptionEn, descriptionRu] = localizedTriplet(data.description_localized, data.description);
  return {
    title, titleEn, titleRu, description, descriptionEn, descriptionRu,
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
  isDormant: boolean;
  data: ClaimEventData | undefined;
  fields: FormFields;
  setField: <K extends keyof FormFields>(key: K, touchKey: TouchKey, value: FormFields[K]) => void;
  isPinned: (field: string, fieldLocale?: string) => boolean;
  unpin: (field: string, fieldLocale?: string) => void;
  unpinning: string | null;
  /** Categories to add on save. The event's total (existing + these) is
   * capped at ORGANIZER_MAX_CATEGORIES, so a toggle is ignored once full. */
  pendingCategories: string[];
  togglePendingCategory: (slug: string) => void;
  uploadImage: (file: File) => void;
  clearImage: () => void;
  imageUploading: boolean;
  imageError: string;
  save: () => void;
  isSaving: boolean;
  saveError: string;
  savedStatus: string | null;
  acceptNewPrice: () => void;
  isAcceptingPrice: boolean;
}

/** Load + save state for the claim-editing surface (#416) — GET/PATCH
 * /organizer/claims/{claimId}/event, or the path-based
 * /organizer/claims/{claimId}/events/{eventId} variant (#453) when targeting
 * one specific covered event. A field only pins when its key is actually
 * included in the PATCH body, so `touched` tracks exactly which fields this
 * session has edited since the last load/save; untouched fields are never
 * sent, however their current value looks. */
export function useClaimEventEdit(
  claimId: number,
  locale: string,
  eventId?: number,
): UseClaimEventEditResult {
  const queryClient = useQueryClient();
  const [fields, setFields] = useState<FormFields>(EMPTY_FIELDS);
  const [touched, setTouched] = useState<Set<TouchKey>>(new Set());
  const [pendingCategories, setPendingCategories] = useState<string[]>([]);
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
      organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId, eventId), {
        unpin: [key],
      }),
    onMutate: (key) => setUnpinningKey(key),
    onSuccess: applyResponse,
    onSettled: () => setUnpinningKey(null),
  });

  const unpin = (field: string, fieldLocale?: string) => {
    unpinMutation.mutate(fieldLocale ? `${field}:${fieldLocale}` : field);
  };

  // Mirrors the backend's own checks (organizer_claim_edits.py's
  // `_non_blank_title`/`ends_at must not be before starts_at`/
  // `validate_price_ordering`) so the common failures never round-trip
  // through a FastAPI 422 at all — those are the real guard, this is only a
  // faster, localized first pass (#452). Scoped to `touched` exactly like
  // the backend's own model only sees keys actually present in the PATCH
  // body — otherwise a pre-existing inconsistency in an untouched field
  // (stale data, a source refetch racing the claim) would block a save that
  // never sends that field and that the backend itself would accept.
  const [clientError, setClientError] = useState('');
  function clientValidationError(): string {
    if (touched.has('title') && !fields.title.trim()) return t('claim_edit_error_blank_title', locale);
    if (
      touched.has('starts_at') && touched.has('ends_at')
      && fields.startsAt && fields.endsAt && fields.endsAt < fields.startsAt
    ) {
      return t('claim_edit_error_end_before_start', locale);
    }
    if (
      touched.has('price_min') && touched.has('price_max')
      && fields.priceMin && fields.priceMax
      && Number(fields.priceMin) > Number(fields.priceMax)
    ) {
      return t('claim_edit_error_price_order', locale);
    }
    return '';
  }

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
      if (pendingCategories.length > 0) body.categories = pendingCategories;
      return organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId, eventId), body);
    },
    onMutate: () => setSavedStatus(null),
    onSuccess: (next) => {
      applyResponse(next);
      setFields(fieldsFromData(next));
      setTouched(new Set());
      setPendingCategories([]);
    },
  });

  // The claim edit accepts only our own Cloudinary uploads as image_url, so
  // the image is uploaded first and its returned URL becomes the field value.
  const imageUpload = useOrganizerImageUpload(locale, (url) => setField('imageUrl', 'image_url', url));

  const acceptPriceMutation = useMutation({
    mutationFn: () =>
      organizerApi.patch<ClaimEventData>(API.organizerClaimEvent(claimId, eventId), {
        accept_new_price: true,
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

  const isLocked = query.isError && query.error instanceof ApiError && query.error.status === StatusCodes.CONFLICT;
  const isDormant =
    isLocked && query.error instanceof ApiError && query.error.code === CLAIM_ERROR_CODE_DORMANT;

  return {
    isLoading: query.isLoading,
    loadError: query.isError && !isLocked ? apiErrorMessage(query.error, t('generic_error', locale)) : '',
    isLocked,
    isDormant,
    data: query.data,
    fields,
    setField,
    isPinned,
    unpin,
    unpinning: unpinningKey,
    pendingCategories,
    togglePendingCategory: (slug: string) => {
      const room = Math.max(0, ORGANIZER_MAX_CATEGORIES - (query.data?.categories.length ?? 0));
      setPendingCategories((prev) => toggleCapped(prev, slug, room));
    },
    uploadImage: imageUpload.upload,
    clearImage: () => { setField('imageUrl', 'image_url', ''); imageUpload.reset(); },
    imageUploading: imageUpload.uploading,
    imageError: imageUpload.error,
    save: () => {
      const err = clientValidationError();
      setClientError(err);
      if (err) return;
      saveMutation.mutate();
    },
    isSaving: saveMutation.isPending,
    saveError: clientError || (saveMutation.isError ? apiErrorMessage(saveMutation.error, t('generic_error', locale)) : ''),
    savedStatus,
    acceptNewPrice: () => acceptPriceMutation.mutate(),
    isAcceptingPrice: acceptPriceMutation.isPending,
  };
}

export type { FormFields as ClaimEventFormFields };
