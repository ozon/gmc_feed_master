import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import {QueryClient} from '@tanstack/react-query';
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

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url.startsWith('/admin/ai/usage')) return jsonResponse({ rows: [] });
    return jsonResponse({});
  });
});


describe('UsagePage', () => {
  it('renders from/to DateInputs and group-by select', async () => {
    render(<UsagePage />);
    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
    expect(screen.getAllByLabelText(/group by/i).length).toBeGreaterThanOrEqual(1);
  });
});
