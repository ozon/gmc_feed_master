import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import {QueryClient} from '@tanstack/react-query';
import { useChat } from './hooks';
import { queryClient as defaultClient } from './queryClient';
import { stubFetch } from '../test/fetch';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}


beforeEach(() => {
  defaultClient.clear();
  vi.restoreAllMocks();
});

describe('useChat', () => {
  it('POSTs the full conversation array to /chat', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/chat' && init?.method === 'POST') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ content: 'hi' });
      }
      return jsonResponse({});
    });

    const conversation = [
      { role: 'user' as const, content: 'what feed sources do I have?' },
      { role: 'assistant' as const, content: 'you have two' },
      { role: 'user' as const, content: 'show findings for the first' },
    ];
    const { result } = renderHook(() => useChat());
    result.current.mutate(conversation);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({ content: 'hi' });
    expect(captured).toEqual({ url: '/chat', body: { messages: conversation } });
  });
});
