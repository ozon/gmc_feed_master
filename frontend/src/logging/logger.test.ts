import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createLogger,
  flushLogs,
  newRequestId,
  resetLogQueue,
} from './logger';

const beaconMock = vi.fn(() => true);

beforeEach(() => {
  resetLogQueue();
  vi.stubGlobal('navigator', { ...navigator, sendBeacon: beaconMock });
  beaconMock.mockReset();
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

  it('generates a request id', () => {
    expect(newRequestId().length).toBeGreaterThan(8);
  });
});
