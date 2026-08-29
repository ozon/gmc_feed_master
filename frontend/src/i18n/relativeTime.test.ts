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
});
