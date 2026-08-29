import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { FindingsTable, type QualityFinding } from './FindingsTable';

const findings: QualityFinding[] = [
  { severity: 'critical', code: 'missing_title', field: 'title', message: 'Title is required', product_id: 'p1', details: {} },
  { severity: 'warning', code: 'low_quality', field: 'image_link', message: 'Low image quality', product_id: 'p2', details: {} },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  notifications.clean();
});

describe('FindingsTable', () => {
  it('renders one row per finding', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getByTestId('finding-row-0')).toBeInTheDocument();
    expect(screen.getByTestId('finding-row-1')).toBeInTheDocument();
  });

  it('renders severity text from the finding', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('warning')).toBeInTheDocument();
  });
});