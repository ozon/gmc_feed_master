import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionDiff } from './ExportVersionDiff';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

describe('ExportVersionDiff', () => {
  it('renders field-based table for changed products', () => {
    render(
      <ExportVersionDiff
        diff={{
          version: 3,
          against: 2,
          added: ['p3'],
          removed: ['p4'],
          changed: [
            {
              product_id: 'p1',
              fields: [{ field: 'title', old: 'Old', new: 'New' }],
            },
          ],
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByTestId('export-version-diff')).toBeInTheDocument();
    expect(screen.getByText('p1')).toBeInTheDocument();
    expect(screen.getByText('title')).toBeInTheDocument();
  });

  it('renders empty state when no changes', () => {
    render(
      <ExportVersionDiff
        diff={{ version: 2, against: 1, added: [], removed: [], changed: [] }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByText(/no changes/i)).toBeInTheDocument();
  });
});