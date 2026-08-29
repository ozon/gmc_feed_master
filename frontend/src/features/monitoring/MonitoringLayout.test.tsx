import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { MonitoringLayout } from './MonitoringLayout';
import { queryClient } from '../../api/queryClient';

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  queryClient.clear();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/clients/:clientId/feeds/:feedSourceId/monitoring/*"
          element={<MonitoringLayout />}
        />
        <Route
          path="/clients/:clientId/feeds/:feedSourceId/monitoring/runs/:runId"
          element={<MonitoringLayout />}
        />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient() },
  );
}

describe('MonitoringLayout', () => {
  it('selects the runs tab on the runs route', () => {
    renderAt('/clients/1/feeds/1/monitoring/runs');
    const tabs = screen.getAllByRole('tab');
    const runsTab = tabs.find((tab) => tab.textContent === 'Runs');
    expect(runsTab).toBeDefined();
    expect(runsTab!).toHaveAttribute('aria-selected', 'true');
  });

  it('selects the findings tab on the findings route', () => {
    renderAt('/clients/1/feeds/1/monitoring/findings');
    const tabs = screen.getAllByRole('tab');
    const findingsTab = tabs.find((tab) => tab.textContent === 'Findings');
    expect(findingsTab).toBeDefined();
    expect(findingsTab!).toHaveAttribute('aria-selected', 'true');
  });

  it('selects the dryRun tab on the dry-run route', () => {
    renderAt('/clients/1/feeds/1/monitoring/dry-run');
    const tabs = screen.getAllByRole('tab');
    const dryRunTab = tabs.find((tab) => tab.textContent === 'Dry run');
    expect(dryRunTab).toBeDefined();
    expect(dryRunTab!).toHaveAttribute('aria-selected', 'true');
  });

  it('still selects the runs tab on a nested runs route', () => {
    renderAt('/clients/1/feeds/1/monitoring/runs/123');
    const tabs = screen.getAllByRole('tab');
    const runsTab = tabs.find((tab) => tab.textContent === 'Runs');
    expect(runsTab).toBeDefined();
    expect(runsTab!).toHaveAttribute('aria-selected', 'true');
  });
});
