import { useMutation } from '@tanstack/react-query';
import { organizerApi } from '../api/client';
import { ORGANIZER_IMAGE_ALLOWED_MIME } from '../_generated/sharedConstants';
import { API } from '../constants/api';
import { t } from '../i18n';
import { apiErrorMessage } from '../utils';

/** Signed Cloudinary upload for an organizer's event image
 * (POST /organizer/events/image), shared by the submission form and the claim
 * edit. `onUploaded` receives the delivery URL to store as `image_url`. */
export function useOrganizerImageUpload(locale: string, onUploaded: (url: string) => void) {
  const mutation = useMutation({
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
    onSuccess: (data) => onUploaded(data.url),
  });

  return {
    upload: mutation.mutate,
    reset: mutation.reset,
    uploading: mutation.isPending,
    error: mutation.isError ? apiErrorMessage(mutation.error, t('generic_error', locale)) : '',
  };
}
