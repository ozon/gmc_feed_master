import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { RecentRunsTable } from './RecentRunsTable';
import type { FeedDashboardData } from '../../api/types';

const runs: FeedDashboardData['recent_runs'] = [
  { id: 2, status: 'success', started_at: '2026-09-12T10:00:00Z', duration_s: 42.5, failed_count: 0 },
  { id: 1, status: 'error', started_at: '2026-09-11T10:00:00Z', duration_s: 12, failed_count: 3 },
];

beforeAll(async () => {
  await i18n.loadNamespaces('feedDashboard');
});

describe('RecentRunsTable', () => {
  it('renders run rows with status, duration, failed count', () => {
    render(<RecentRunsTable runs={runs} />);
    expect(screen.getByTestId('run-row-2')).toBeInTheDocument();
    expect(screen.getByTestId('run-row-1')).toBeInTheDocument();
    expect(screen.getByText('42.5s')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders the empty state when no runs', () => {
    render(<RecentRunsTable runs={[]} />);
    expect(screen.getByText('No runs yet.')).toBeInTheDocument();
  });
});
