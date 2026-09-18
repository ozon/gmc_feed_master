import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createLogger,
  flushLogs,
  newRequestId,
  resetLogQueue,
} from './logger';

const beaconMock = vi.fn(() => true);
const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));

beforeEach(() => {
  resetLogQueue();
  vi.stubGlobal('navigator', { ...navigator, sendBeacon: beaconMock });
  vi.stubGlobal('fetch', fetchMock);
  beaconMock.mockReset();
  fetchMock.mockReset();
});

describe('logger', () => {
  it('does not ship debug/info', () => {
    const log = createLogger('test');
    log.info('hello');
    flushLogs();
    expect(beaconMock).not.toHaveBeenCalled();
  });

  it('ships errors with redacted context', () => {
    const log = createLogger('test');
    log.error('failed', { password: 'hunter2', keep: 'value' });
    flushLogs();
    expect(beaconMock).toHaveBeenCalledTimes(1);
    const [url, blob] = beaconMock.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe('/logs/client');
    return blob.text().then((text) => {
      const payload = JSON.parse(text) as {
        entries: Array<{ context: Record<string, unknown>; level: string }>;
      };
      expect(payload.entries[0].level).toBe('error');
      expect(payload.entries[0].context.password).toBe('[REDACTED]');
      expect(payload.entries[0].context.keep).toBe('value');
    });
  });

  it('ships warn as warning (backend ships "warning", not "warn")', () => {
    const log = createLogger('test');
    log.warn('careful');
    flushLogs();
    expect(beaconMock).toHaveBeenCalledTimes(1);
    const [url, blob] = beaconMock.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe('/logs/client');
    return blob.text().then((text) => {
      const payload = JSON.parse(text) as {
        entries: Array<{ level: string }>;
      };
      expect(payload.entries[0].level).toBe('warning');
    });
  });

  it('falls back to fetch when sendBeacon returns false', () => {
    beaconMock.mockReturnValueOnce(false);
    const log = createLogger('test');
    log.error('beacon refused');
    flushLogs();
    expect(beaconMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe('POST');
  });

  it('keeps route and url distinct and strips url query', () => {
    const log = createLogger('test');
    log.error('failed request', { url: '/orders?token=secret' });
    flushLogs();
    const [, blob] = beaconMock.mock.calls[0] as unknown as [string, Blob];
    return blob.text().then((text) => {
      const payload = JSON.parse(text) as {
        entries: Array<{ route: string; url: string }>;
      };
      expect(payload.entries[0].url).toBe('/orders');
      expect(payload.entries[0].route).toBe(window.location.pathname);
    });
  });

  it('caps the shipped message at the 2000-char API limit', () => {
    const log = createLogger('test');
    log.error('x'.repeat(5000));
    flushLogs();
    const [, blob] = beaconMock.mock.calls[0] as unknown as [string, Blob];
    return blob.text().then((text) => {
      const payload = JSON.parse(text) as { entries: Array<{ message: string }> };
      expect(payload.entries[0].message.length).toBeLessThanOrEqual(2000);
    });
  });

  it('generates a request id', () => {
    expect(newRequestId().length).toBeGreaterThan(8);
  });
});
