import { describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';

describe('queryKeys', () => {
  it('builds stable top-level keys', () => {
    expect(queryKeys.session).toEqual(['session']);
    expect(queryKeys.dashboardSummary).toEqual(['dashboard', 'summary']);
    expect(queryKeys.plugins).toEqual(['plugins']);
  });

  it('nests feed-source keys by id and area', () => {
    expect(queryKeys.feedSource(7).pipeline).toEqual(['feed-source', 7, 'pipeline']);
    expect(queryKeys.feedSource(7).products({ page: 1 })).toEqual([
      'feed-source',
      7,
      'products',
      { page: 1 },
    ]);
  });
});
