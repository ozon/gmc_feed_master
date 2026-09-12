import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { SystemLogsPage } from './SystemLogsPage';

beforeAll(async () => {
  await i18n.loadNamespaces(['systemLogs']);
});

describe('SystemLogsPage', () => {
  it('renders the coming-soon empty state', () => {
    render(<SystemLogsPage />);
    expect(screen.getByRole('heading', { name: /system logs/i })).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});
