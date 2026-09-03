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
  { name: 'title', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'description', kind: 'scalar', required: 'optional', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'id', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'brand', kind: 'scalar', required: 'required', baseline_required: false, sub_fields: [], enum_values: [] },
  { name: 'installment', kind: 'structured', required: 'optional', baseline_required: false, sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [] },
  { name: 'link', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'image_link', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'availability', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'price', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'condition', kind: 'scalar', required: 'required', baseline_required: true, sub_fields: [], enum_values: [] },
  { name: 'structured_title', kind: 'structured', required: 'optional', baseline_required: true, sub_fields: [], enum_values: [] },
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

  it('shows required-uncovered alert for uncovered baseline attrs only', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    expect(await screen.findByText(/required registry attributes not covered/i)).toBeInTheDocument();
    expect(screen.getAllByText(/id/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/the following required attributes are not mapped/i)).not.toHaveTextContent(/brand/i);
    expect(screen.getAllByText(/price/i).length).toBeGreaterThanOrEqual(1);
  });

  it('structured_title alone covers the title pair', async () => {
    const altDoc: FieldMappingDoc = {
      ...mappingDoc,
      mappings: {
        title: { target: 'structured_title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
      },
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(altDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    const alertBody = await screen.findByText(/the following required attributes are not mapped/i);
    expect(alertBody).not.toHaveTextContent(/title/i);
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

  it('save PUTs the full mapping set, not only local edits', async () => {
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

    // Edit a single row; the untouched server-side mappings must survive the PUT.
    const productRow = screen.getByText('synonym_field').closest('tr')!;
    const select = productRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^brand$/ });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual({
        title: { target: 'title' },
        description: { target: 'description' },
        synonym_field: { target: 'brand' },
      });
    });
  });

  it('save excludes rows whose target was cleared', async () => {
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

    // Clear the description mapping; it must be absent from the PUT body.
    // Scope to the row whose source-field name is exactly 'description';
    // the select value/option text also contains 'description'.
    const descriptionRow = screen
      .getAllByText('description')
      .map((el) => el.closest('tr'))
      .find((tr) => {
        const sourceCell = tr?.querySelector('td p');
        return sourceCell?.textContent === 'description';
      });
    expect(descriptionRow).toBeDefined();
    const clearButton = descriptionRow!.querySelector('.mantine-InputClearButton-root');
    expect(clearButton).not.toBeNull();
    await user.click(clearButton!);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual({
        title: { target: 'title' },
        synonym_field: { target: 'description' },
      });
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
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'link', kind: 'scalar', sub_fields: [] },
        { name: 'image_link', kind: 'scalar', sub_fields: [] },
        { name: 'availability', kind: 'scalar', sub_fields: [] },
        { name: 'price', kind: 'scalar', sub_fields: [] },
        { name: 'condition', kind: 'scalar', sub_fields: [] },
      ],
      mappings: {
        title: { target: 'title', origin: 'auto' },
        description: { target: 'description', origin: 'auto' },
        product_id: { target: 'id', origin: 'auto' },
        synonym_field: { target: 'brand', origin: 'manual' },
        link: { target: 'link', origin: 'auto' },
        image_link: { target: 'image_link', origin: 'auto' },
        availability: { target: 'availability', origin: 'auto' },
        price: { target: 'price', origin: 'auto' },
        condition: { target: 'condition', origin: 'auto' },
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

  it('save PUTs dotted sub-field keys and clears the conflicting parent edit', async () => {
    const user = userEvent.setup();
    const doc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'ship', kind: 'structured', sub_fields: ['country'] },
      ],
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...doc, auto_mapped: false });
        }
        return jsonResponse(doc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('ship')).toBeInTheDocument();
    });

    const toggle = document.querySelector('[data-sub-toggle="ship"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('country', { selector: 'td p' })).closest('tr')!;
    const select = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: 'installment.months' });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual(
        expect.objectContaining({
          'ship.country': { target: 'installment.months' },
        }),
      );
      expect((body?.mappings as Record<string, unknown>)['ship']).toBeUndefined();
    });
  });

  it('sub-field edit removes the server-side parent mapping from the PUT payload', async () => {
    const user = userEvent.setup();
    const doc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'ship', kind: 'structured', sub_fields: ['country'] },
      ],
      mappings: {
        ...mappingDoc.mappings,
        ship: { target: 'installment', origin: 'manual' },
      },
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...doc, auto_mapped: false });
        }
        return jsonResponse(doc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('ship')).toBeInTheDocument();
    });

    const toggle = document.querySelector('[data-sub-toggle="ship"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('country', { selector: 'td p' })).closest('tr')!;
    const select = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: 'installment.months' });
    await user.click(option);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual(
        expect.objectContaining({
          'ship.country': { target: 'installment.months' },
        }),
      );
      expect((body?.mappings as Record<string, unknown>)['ship']).toBeUndefined();
    });
  });

  it('parent edit clears pending sub-field edits from the PUT payload', async () => {
    const user = userEvent.setup();
    const doc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [
        ...mappingDoc.source_fields,
        { name: 'ship', kind: 'structured', sub_fields: ['country'] },
      ],
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...doc, auto_mapped: false });
        }
        return jsonResponse(doc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();

    await waitFor(() => {
      expect(screen.getByText('ship')).toBeInTheDocument();
    });

    const toggle = document.querySelector('[data-sub-toggle="ship"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('country', { selector: 'td p' })).closest('tr')!;
    const subSelect = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(subSelect);
    const subOption = await screen.findByRole('option', { name: 'installment.months' });
    await user.click(subOption);

    const parentRow = document.querySelector('[data-sub-toggle="ship"]')!.closest('tr')!;
    const parentSelect = parentRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(parentSelect);
    const parentOption = await screen.findByRole('option', { name: /^brand$/ });
    await user.click(parentOption);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.mappings).toEqual(
        expect.objectContaining({
          ship: { target: 'brand' },
        }),
      );
      expect((body?.mappings as Record<string, unknown>)['ship.country']).toBeUndefined();
    });
  });
});
