import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { UsagePage } from './UsagePage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const SUMMARY = {
  calls: 42,
  cache_hits: 21,
  hit_ratio: 0.5,
  prompt_tokens: 100,
  completion_tokens: 20,
  cost_usd: '1.50',
  saved_prompt_tokens: 10,
  saved_completion_tokens: 2,
  cost_saved_usd: '0.25',
};

const USAGE_ROW = {
  group_key: 1,
  calls: 42,
  cache_hits: 21,
  prompt_tokens: 100,
  completion_tokens: 20,
  cost_usd: '1.50',
};

const TREND_ROWS = [
  {
    group_key: '2026-09-15',
    calls: 20,
    cache_hits: 10,
    prompt_tokens: 50,
    completion_tokens: 10,
    cost_usd: '0.75',
  },
  {
    group_key: '2026-09-16',
    calls: 22,
    cache_hits: 11,
    prompt_tokens: 50,
    completion_tokens: 10,
    cost_usd: '0.75',
  },
];

function stubUsage({ rows = [USAGE_ROW], trend = TREND_ROWS } = {}) {
  stubFetch((url) => {
    if (url.startsWith('/admin/ai/usage/summary')) return jsonResponse(SUMMARY);
    if (url.startsWith('/admin/ai/usage/timeseries')) return jsonResponse({ rows: trend });
    if (url.startsWith('/admin/ai/usage')) return jsonResponse({ rows });
    return jsonResponse({});
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubUsage();
});

async function renderPage() {
  render(<UsagePage />);
  await waitFor(() => {
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
}

describe('UsagePage', () => {
  it('renders from/to DateInputs and group-by select', async () => {
    await renderPage();
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
    expect(screen.getAllByLabelText(/group by/i).length).toBeGreaterThanOrEqual(1);
  });

  it('renders the KPI row from the usage summary', async () => {
    await renderPage();
    await waitFor(() => {
      expect(screen.getByText('Total calls')).toBeInTheDocument();
    });
    const kpi = within(screen.getByTestId('ai-usage-kpi'));
    expect(kpi.getByText('42')).toBeInTheDocument();
    expect(kpi.getByText('50%')).toBeInTheDocument();
    expect(kpi.getByText('1.5')).toBeInTheDocument();
    expect(kpi.getByText('0.25')).toBeInTheDocument();
  });

  it('renders the trend chart when timeseries rows exist', async () => {
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('chart-card')).toBeInTheDocument();
    });
    expect(screen.queryByText('No AI usage recorded yet')).not.toBeInTheDocument();
  });

  it('shows the empty trend state when there are no timeseries rows', async () => {
    stubUsage({ trend: [] });
    await renderPage();
    await waitFor(() => {
      expect(screen.getAllByText('No AI usage recorded yet').length).toBeGreaterThan(0);
    });
  });
});
