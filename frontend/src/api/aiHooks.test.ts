import { describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';

describe('ai query keys', () => {
  it('exposes stable provider keys', () => {
    expect(queryKeys.ai.providers).toEqual(['ai', 'providers']);
  });

  it('builds usage keys from params', () => {
    expect(queryKeys.ai.usage({ group_by: 'client' })).toEqual([
      'ai',
      'usage',
      { group_by: 'client' },
    ]);
  });
});
