import { notifyError } from './notifications';
import { ApiError } from '../api/client';

export function mapFieldErrors(errors: string[] | null): Record<string, string> {
  if (!errors) return {};
  const out: Record<string, string> = {};
  for (const e of errors) {
    const idx = e.indexOf(':');
    if (idx > 0) {
      out[e.slice(0, idx).trim()] = e.slice(idx + 1).trim();
    } else {
      out._form = e;
    }
  }
  return out;
}

export function notifyApiError(
  error: unknown,
  fallback: string,
  errorsSummary?: string,
): Record<string, string> {
  if (error instanceof ApiError && error.errors && error.errors.length > 0) {
    notifyError(errorsSummary ?? error.errors.join('; '));
    return mapFieldErrors(error.errors);
  }
  if (error instanceof ApiError && error.detail) {
    notifyError(error.detail);
    return {};
  }
  notifyError(fallback);
  return {};
}
