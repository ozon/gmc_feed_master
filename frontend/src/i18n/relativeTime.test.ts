import { describe, expect, it } from 'vitest';
import dayjs from 'dayjs';
import 'dayjs/locale/de';
import { registerRelativeTime } from './relativeTime';

describe('registerRelativeTime', () => {
  it('is idempotent and enables fromNow', () => {
    registerRelativeTime();
    registerRelativeTime();
    expect(dayjs().subtract(2, 'day').fromNow()).toContain('2 days');
  });

  it('formats German relative times from the dayjs de locale', () => {
    registerRelativeTime();
    expect(dayjs().locale('de').subtract(2, 'day').fromNow()).toBe('vor 2 Tagen');
    expect(dayjs().locale('de').subtract(2, 'day').fromNow()).toContain('vor');
  });

  it('enables localized date format tokens', () => {
    registerRelativeTime();
    expect(dayjs('2026-09-12T10:00:00Z').locale('en').format('L LTS')).toBe(
      '09/12/2026 10:00:00 AM',
    );
    expect(dayjs('2026-09-12T10:00:00Z').locale('de').format('L LTS')).toBe('12.09.2026 10:00:00');
  });
});
