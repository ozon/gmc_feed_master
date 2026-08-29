import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';
import type { ProductsPageResponse, ProductDetail } from '../../api/types';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const page1Items = Array.from({ length: 5 }, (_, i) => ({
  product_id: `pid-${i + 1}`,
  id: `id-${i + 1}`,
  status: i === 0 ? 'removed' : 'active',
  last_seen_at: '2026-08-28T12:00:00Z',
  title: `Product ${i + 1}`,
  description: `Description ${i + 1}`,
  link: `https://example.com/${i + 1}`,
  image_link: `https://img.example.com/${i + 1}.jpg`,
  availability: 'in_stock',
  price: `${(i + 1) * 10}.99`,
  condition: 'new',
}));

const page2Items = Array.from({ length: 2 }, (_, i) => ({
  product_id: `pid-${i + 6}`,
  id: `id-${i + 6}`,
  status: 'active',
  last_seen_at: '2026-08-28T12:00:00Z',
  title: `Product ${i + 6}`,
  description: `Description ${i + 6}`,
  link: `https://example.com/${i + 6}`,
  image_link: `https://img.example.com/${i + 6}.jpg`,
  availability: 'in_stock',
  price: `${(i + 6) * 10}.99`,
  condition: 'new',
}));

const productsPage1: ProductsPageResponse = {
  items: page1Items,
  total: 7,
  page: 1,
  page_size: 5,
};

const productsPage2: ProductsPageResponse = {
  items: page2Items,
  total: 7,
  page: 2,
  page_size: 5,
};

const productDetail: ProductDetail = {
  product_id: 'pid-1',
  status: 'removed',
  content_hash: 'abc123',
  config_hash: 'def456',
  last_seen_at: '2026-08-28T12:00:00Z',
  removed_at: '2026-08-29T00:00:00Z',
  raw_data: { title: 'Product 1', price: '10.99', custom_field: 'test-value-42' },
};

let fetchMock: ReturnType<typeof stubFetch>;

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/clients/1/feeds/2/products');
  localStorage.clear();
});

function setupFetch(handler: (url: string) => Response | Promise<Response>) {
  fetchMock = stubFetch((url) => {
    if (url === '/auth/me') return jsonResponse({ username: 'operator' });
    if (url === '/plugins') return jsonResponse([]);
    return handler(url);
  });
}

describe('ProductsPage', () => {
  it('renders rows, total count and pagination', async () => {
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByText('Product 1')).toBeInTheDocument();
    expect(screen.getByText('Product 5')).toBeInTheDocument();
    expect(screen.getByText(/7 items/)).toBeInTheDocument();
  });

  it('navigates to next page via page param', async () => {
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) {
        const params = new URL(url, 'http://localhost');
        const p = params.searchParams.get('page') ?? '1';
        if (p === '2') return jsonResponse(productsPage2);
        return jsonResponse(productsPage1);
      }
      return jsonResponse({});
    });

    window.history.replaceState({}, '', '/clients/1/feeds/2/products?page=2');
    render(<App />);

    expect(await screen.findByText('Product 6')).toBeInTheDocument();
    expect(screen.queryByText('Product 1')).not.toBeInTheDocument();
  });

  it('changes page size', async () => {
    const user = userEvent.setup();
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const pageSizeSelect = screen.getByRole('combobox', { name: /rows per page/i });
    await user.click(pageSizeSelect);
    await user.click(screen.getByRole('option', { name: '25' }));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(
        ([input]) => String(input).includes('page_size=25'),
      );
      expect(calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('searches products with debounce', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const searchInput = screen.getByPlaceholderText(/search products/i);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(searchInput, 'sock');

    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(
        ([input]) => String(input).includes('q=sock'),
      );
      expect(calls.length).toBeGreaterThanOrEqual(1);
    });

    vi.useRealTimers();
  });

  it('filters by status', async () => {
    const user = userEvent.setup();
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const statusSelect = screen.getByRole('combobox', { name: /status/i });
    await user.click(statusSelect);
    await user.click(screen.getByRole('option', { name: /removed/i }));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(
        ([input]) => String(input).includes('status=removed'),
      );
      expect(calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('persists column picker to localStorage', async () => {
    const user = userEvent.setup();
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const columnsBtn = screen.getByRole('button', { name: /columns/i });
    await user.click(columnsBtn);

    const conditionCheckbox = await screen.findByRole('checkbox', { name: /condition/i });
    await user.click(conditionCheckbox);

    const stored = JSON.parse(
      localStorage.getItem('products.columns.2') ?? '[]',
    ) as string[];
    expect(stored).not.toContain('condition');
  });

  it('opens drawer on row click with raw_data', async () => {
    const user = userEvent.setup();
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products/pid-1')) return jsonResponse(productDetail);
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    await user.click(screen.getByText('Product 1'));

    expect(await screen.findByText('Product Details')).toBeInTheDocument();
    expect(screen.getByText(/test-value-42/)).toBeInTheDocument();
  });

  it('renders badge for removed item', async () => {
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const table = screen.getByRole('table');
    const rows = table.querySelectorAll('tbody tr');
    const firstRow = rows[0];
    expect(firstRow).toBeTruthy();
    expect(firstRow.querySelector('[class*="Badge"]')).toBeInTheDocument();
  });

  it('Processed segment is disabled', async () => {
    setupFetch((url) => {
      if (url.includes('/feed-sources/2/products')) return jsonResponse(productsPage1);
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByText('Product 1');

    const processed = screen.getByText(/processed/i);
    expect(processed.closest('[data-disabled]')).toBeTruthy();
  });
});
