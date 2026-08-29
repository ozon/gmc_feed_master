import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../api/client';
import { mapFieldErrors, notifyApiError } from './notifyApiError';
import { notifyApiError as notifyApiErrorViaNotifications } from './notifications';

const showMock = vi.fn();

beforeEach(() => {
  showMock.mockClear();
  vi.spyOn(notifications, 'show').mockImplementation(showMock);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('notifyApiError', () => {
  it('joins ApiError errors into one toast and returns the field map', () => {
    const error = new ApiError(422, undefined, ['name: too short', 'email is invalid']);
    const map = notifyApiError(error, 'Save failed');
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'name: too short; email is invalid',
        color: 'red',
        autoClose: false,
      }),
    );
    expect(map).toEqual({ name: 'too short', _form: 'email is invalid' });
  });

  it('shows the provided errorsSummary instead of the raw join', () => {
    const error = new ApiError(422, undefined, ['name: too short']);
    const map = notifyApiError(error, 'Save failed', '2 fields failed');
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({
        message: '2 fields failed',
        color: 'red',
        autoClose: false,
      }),
    );
    expect(map).toEqual({ name: 'too short' });
  });

  it('shows the ApiError detail when there are no field errors', () => {
    const error = new ApiError(422, 'name already exists');
    expect(notifyApiError(error, 'Save failed')).toEqual({});
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'name already exists' }),
    );
  });

  it('shows the ApiError detail when the errors array is empty', () => {
    const error = new ApiError(422, 'invalid body', []);
    expect(notifyApiError(error, 'Save failed')).toEqual({});
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'invalid body' }),
    );
  });

  it('uses the fallback for a plain Error', () => {
    expect(notifyApiError(new Error('boom'), 'Save failed')).toEqual({});
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Save failed' }),
    );
  });

  it('uses the fallback for a non-Error value', () => {
    expect(notifyApiError('oops', 'Save failed')).toEqual({});
    expect(showMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Save failed' }),
    );
  });

  it('is re-exported from notifications.ts', () => {
    expect(notifyApiErrorViaNotifications).toBe(notifyApiError);
  });
});

describe('mapFieldErrors', () => {
  it('returns an empty map for null', () => {
    expect(mapFieldErrors(null)).toEqual({});
  });

  it('splits on the first colon and trims key and value', () => {
    expect(mapFieldErrors([' url : https://example.com ', 'empty:'])).toEqual({
      url: 'https://example.com',
      empty: '',
    });
  });

  it('sends entries without a field key to _form', () => {
    expect(mapFieldErrors(['global failure', ':no key'])).toEqual({
      _form: ':no key',
    });
  });
});
