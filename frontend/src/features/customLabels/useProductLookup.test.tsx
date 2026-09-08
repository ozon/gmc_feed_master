import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { useProductLookup } from '../../api/hooks';

function withClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const RESPONSE = {
  matches: {
    a1: {
      count: 1,
      sample: {
        product_id: 'a1', status: 'active', excluded: false,
        title: 'Alpha', brand: 'Acme', availability: 'in_stock',
      },
    },
    zz: { count: 0, sample: null },
  },
};

function Probe(props: { feedSourceId?: number; field?: string; values?: string[]; extraFields?: string[] }) {
  const query = useProductLookup(
    props.feedSourceId,
    props.field ?? 'id',
    props.values ?? [],
    props.extraFields ?? [],
  );
  return (
    <div>
      <span data-testid="pending">{String(query.isPending)}</span>
      <span data-testid="count">{query.data?.matches.a1?.count ?? ''}</span>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useProductLookup', () => {
  it('posts the lookup body and returns the mapped response', async () => {
    const bodies: unknown[] = [];
    stubFetch((url, init) => {
      if (url.includes('/products/lookup')) {
        bodies.push(JSON.parse(String(init?.body)));
        return jsonResponse(RESPONSE);
      }
      return jsonResponse({});
    });
    const Wrapper = withClient();
    render(<Wrapper><Probe feedSourceId={3} values={['a1', 'zz']} extraFields={['price']} /></Wrapper>);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="count"]')?.textContent).toBe('1'),
      { timeout: 5000 },
    )).toBeTruthy();
    expect(bodies).toEqual([
      { field: 'id', values: ['a1', 'zz'], extraFields: ['price'] },
    ]);
  });

  it('sends no request without a feed source or with no values', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponse({});
    });
    const A = withClient();
    render(<A><Probe values={['a1']} /></A>);
    const B = withClient();
    render(<B><Probe feedSourceId={3} values={[]} /></B>);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(calls.some((u) => u.includes('/products/lookup'))).toBe(false);
  });
});
