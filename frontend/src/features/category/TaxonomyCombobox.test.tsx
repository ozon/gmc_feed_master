import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { TaxonomyCombobox } from './TaxonomyCombobox';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces('category');
});

beforeEach(() => {
  vi.restoreAllMocks();
});

function renderCombobox() {
  return render(<TaxonomyCombobox language="de" value={null} onChange={() => {}} />);
}

describe('TaxonomyCombobox', () => {
  it('shows debounced search results', async () => {
    const user = userEvent.setup();
    stubFetch(() =>
      jsonResponse({ items: [{ id: '1234', path: 'Apparel > Shoes' }] }),
    );

    renderCombobox();

    await user.type(screen.getByPlaceholderText(/search category/i), 'shoes');

    expect(await screen.findByText('1234 — Apparel > Shoes')).toBeInTheDocument();
  });

  it('surfaces a search failure instead of the no-results message', async () => {
    const user = userEvent.setup();
    stubFetch(() => jsonResponse({ detail: 'boom' }, 500));

    renderCombobox();

    await user.type(screen.getByPlaceholderText(/search category/i), 'shoes');

    expect(await screen.findByText('Could not search categories.')).toBeInTheDocument();
    expect(screen.queryByText('No matching category.')).not.toBeInTheDocument();
  });
});
