import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { IngestionRunsTable, type IngestionRun } from './IngestionRunsTable';

const runs: IngestionRun[] = [
  {
    id: 1,
    status: 'success',
    started_at: '2026-08-29T10:00:00Z',
    completed_at: '2026-08-29T10:01:00Z',
    processed_count: 100,
    failed_count: 2,
    error_message: null,
    statistics: {},
  },
  {
    id: 2,
    status: 'error',
    started_at: '2026-08-29T11:00:00Z',
    completed_at: '2026-08-29T11:05:00Z',
    processed_count: 10,
    failed_count: 5,
    error_message: 'Boom',
    statistics: {},
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  notifications.clean();
});

describe('IngestionRunsTable', () => {
  it('renders one row per run', () => {
    render(<IngestionRunsTable runs={runs} />);
    expect(screen.getByTestId('run-row-1')).toBeInTheDocument();
    expect(screen.getByTestId('run-row-2')).toBeInTheDocument();
  });

  it('shows error_message text when present', () => {
    render(<IngestionRunsTable runs={runs} />);
    expect(screen.getByText('Boom')).toBeInTheDocument();
  });
});