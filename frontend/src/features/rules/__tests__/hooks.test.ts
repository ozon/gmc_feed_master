import { beforeEach, describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import { makeTestQueryClient, renderHook } from '../../../test/render';
import { requestBody, stubFetch } from '../../../test/fetch';
import { queryKeys } from '../../../api/queryKeys';
import { useSaveAiRules } from '../hooks';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const aiRules = { enabled: true, limit: 5, budget: 10 };

let queryClient: QueryClient;
let fetchMock: ReturnType<typeof stubFetch>;

beforeEach(() => {
  queryClient = makeTestQueryClient();
  fetchMock = stubFetch((url, init) => {
    if (url === '/feed-sources/1') {
      return init?.method === 'PUT'
        ? jsonResponse({ id: 1 })
        : jsonResponse({ id: 1, configuration: { sibling: 'keep' } });
    }
    return jsonResponse({});
  });
});

function putBody(): { configuration: Record<string, unknown> } {
  const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
  expect(putCall).toBeTruthy();
  return JSON.parse(requestBody(putCall![1]));
}

describe('useSaveAiRules', () => {
  it('preserves cached sibling configuration keys when saving ai_rules', async () => {
    queryClient.setQueryData(queryKeys.feedSource(1).detail, {
      id: 1,
      configuration: { other: 1 },
    });

    const { result } = renderHook(() => useSaveAiRules(1), { queryClient });
    result.current.mutate(aiRules);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(putBody().configuration).toEqual({ other: 1, ai_rules: aiRules });
  });

  it('fetches the feed source before saving when the cache is empty', async () => {
    const { result } = renderHook(() => useSaveAiRules(1), { queryClient });
    result.current.mutate(aiRules);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/feed-sources/1')).toBe(true);
    expect(putBody().configuration).toEqual({ sibling: 'keep', ai_rules: aiRules });
  });
});
