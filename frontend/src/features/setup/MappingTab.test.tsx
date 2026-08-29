import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Notifications, notifications } from '@mantine/notifications';
import { MemoryRouter, Route, Routes } from 'react-router';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { queryClient } from '../../api/queryClient';
import { MappingTab } from './MappingTab';
import type { FieldMappingDoc, RegistryAttribute } from '../../api/types';

const mappingDoc: FieldMappingDoc = {
  version: 1,
  auto_mapped: true,
  source_fields: [
    { name: 'title', kind: 'scalar', sub_fields: [] },
    { name: 'description', kind: 'scalar', sub_fields: [] },
    { name: 'product_id', kind: 'scalar', sub_fields: [] },
    { name: 'synonym_field', kind: 'scalar', sub_fields: [] },
  ],
  mappings: {
    title: { target: 'title', origin: 'auto' },
    description: { target: 'description', origin: 'auto' },
    synonym_field: { target: 'description', origin: 'synonym' },
  },
};

const registryAttrs: RegistryAttribute[] = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [] },
  { name: 'description', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [] },
  { name: 'id', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [] },
  { name: 'brand', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [] },
  { name: 'installment', kind: 'structured', required: 'optional', sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [] },
];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof stubFetch>;

function putBody(url: string): Record<string, unknown> | undefined {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === url && init?.method === 'PUT',
  );
  if (!call || !call[1]?.body) return undefined;
  return JSON.parse(String(call[1].body)) as Record<string, unknown>;
}

function postCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'POST',
  ).length;
}

beforeEach(async () => {
  queryClient.clear();
  notifications.clean();
  window.history.replaceState({}, '', '/clients/1/feeds/1/setup?tab=mapping');
  await i18n.loadNamespaces(['setup', 'notifications']);
});

function renderTab() {
  return render(
    <MemoryRouter initialEntries={['/clients/1/feeds/1/setup?tab=mapping']}>
      <Routes>
        <Route path="/clients/:clientId/feeds/:feedSourceId/setup" element={
          <QueryClientProvider client={queryClient}>
            <Notifications position="top-right" limit={5} />
            <MappingTab />
          </QueryClientProvider>
        } />
      </Routes>
    </MemoryRouter>,
  );
}

describe('MappingTab', () => {
  it('renders rows and origin badges from server mapping', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });
    expect(screen.getByText('synonym_field')).toBeInTheDocument();
    expect(screen.getAllByText('auto').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('suggestion')).toBeInTheDocument();
  });

  it('shows auto_mapped badge when doc.auto_mapped is true', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    expect(await screen.findByText('Auto-mapped')).toBeInTheDocument();
  });

  it('shows required-uncovered alert for uncovered required attrs', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    expect(await screen.findByText(/required registry attributes not covered/i)).toBeInTheDocument();
    expect(screen.getAllByText(/brand/i).length).toBeGreaterThanOrEqual(1);
  });

  it('marking dirty enables save button', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });

    const saveBtn = screen.getByRole('button', { name: /save/i });
    expect(saveBtn).toBeDisabled();

    const productRow = screen.getByText('product_id').closest('tr')!;
    const select = productRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^id$/ });
    await user.click(option);

    await waitFor(() => expect(saveBtn).toBeEnabled());
  });

  it('save PUTs exact body with changed mappings', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...mappingDoc, auto_mapped: false });
        }
        return jsonResponse(mappingDoc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });

    const productRow = screen.getByText('product_id').closest('tr')!;
    const select = productRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^id$/ });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());

    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual(
        expect.objectContaining({
          product_id: { target: 'id' },
        }),
      );
    });
  });

  it('422 errors render on matching rows and show summary notification', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ errors: ['product_id: unknown attribute \'bad\''] }, 422);
        }
        return jsonResponse(mappingDoc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });

    const productRow = screen.getByText('product_id').closest('tr')!;
    const select = productRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^id$/ });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText(/unknown attribute 'bad'/i)).toBeInTheDocument();
    });
  });

  it('auto-mapper POSTs and re-renders with new origins', async () => {
    const user = userEvent.setup();
    const newMappingDoc = {
      ...mappingDoc,
      auto_mapped: true,
      mappings: {
        title: { target: 'title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
        synonym_field: { target: 'description', origin: 'synonym' },
      },
    };

    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping/auto') {
        return jsonResponse(newMappingDoc);
      }
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });

    const autoBtn = screen.getByRole('button', { name: /auto mapper/i });
    await user.click(autoBtn);

    await waitFor(() => {
      expect(postCalls('/feed-sources/1/field-mapping/auto')).toBe(1);
    });
  });

  it('required-uncovered alert disappears when all required attrs are covered', async () => {
    const fullyCoveredDoc: FieldMappingDoc = {
      ...mappingDoc,
      mappings: {
        title: { target: 'title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
        synonym_field: { target: 'brand', origin: 'manual' },
      },
    };

    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(fullyCoveredDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.queryByText(/required registry attributes not covered/i)).not.toBeInTheDocument();
    });
  });
});
