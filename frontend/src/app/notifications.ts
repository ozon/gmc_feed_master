import { notifications } from '@mantine/notifications';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/client';

export { notifyApiError, mapFieldErrors } from './notifyApiError';

export function notifySuccess(message: string) {
  notifications.show({ color: 'teal', message, autoClose: 4000 });
}

export function notifyError(message: string) {
  notifications.show({ color: 'red', message, autoClose: false });
}

export function notifyMutationError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.detail) {
    notifyError(error.detail);
    return;
  }
  notifyError(fallback);
}

export function withLoadingNotification<T>(
  id: string,
  loadingMessage: string,
  action: () => Promise<T>,
  successMessage: string,
  failureMessage: string,
): Promise<T> {
  notifications.show({ id, loading: true, message: loadingMessage, autoClose: false });
  return action()
    .then((result) => {
      notifications.update({ id, color: 'teal', message: successMessage, loading: false, autoClose: 4000 });
      return result;
    })
    .catch((error) => {
      notifications.update({ id, color: 'red', message: failureMessage, loading: false, autoClose: false });
      throw error;
    });
}

export type RunStatusView = { id: number; status: string };

export function useRunTransitionNotifier(runs: RunStatusView[] | undefined) {
  const { t } = useTranslation('notifications');
  const seen = useRef<Map<number, string>>(new Map());

  useEffect(() => {
    if (!runs) return;
    for (const run of runs) {
      const previous = seen.current.get(run.id);
      if (previous === 'running' && run.status === 'success') {
        notifySuccess(t('runFinished'));
      } else if (previous === 'running' && run.status === 'error') {
        notifyError(t('runFailed'));
      }
      seen.current.set(run.id, run.status);
    }
  }, [runs, t]);
}
