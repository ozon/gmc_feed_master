import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionList } from './ExportVersionList';
import type { ExportVersionOut } from '../../api/types';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

const versions: ExportVersionOut[] = [
  {
    id: 3,
    version_number: 3,
    product_count: 100,
    file_hash: 'h3',
    source: 'scheduled',
    source_version_id: null,
    created_at: '2026-08-29T10:00:00Z',
    findings: { critical: 0, warning: 0, info: 0 },
  },
  {
    id: 1,
    version_number: 1,
    product_count: 90,
    file_hash: 'h1',
    source: 'manual',
    source_version_id: null,
    created_at: '2026-08-27T10:00:00Z',
    findings: { critical: 0, warning: 0, info: 0 },
  },
];

function setup() {
  const onPreview = vi.fn<(v: number) => void>();
  const onDownload = vi.fn<(v: number) => void>();
  render(
    <ExportVersionList
      versions={versions}
      versionA={undefined}
      versionB={undefined}
      onSelectA={() => {}}
      onSelectB={() => {}}
      onRollback={() => {}}
      onPreview={onPreview}
      onDownload={onDownload}
    />,
  );
  return { onPreview, onDownload };
}

describe('ExportVersionList', () => {
  it('marks only the newest version as live', () => {
    setup();
    expect(screen.getAllByTestId('live-badge')).toHaveLength(1);
    expect(screen.getByTestId('version-row-3').textContent).toContain('Live');
  });

  it('invokes preview and download per row', async () => {
    const user = userEvent.setup();
    const { onPreview, onDownload } = setup();
    await user.click(screen.getByTestId('preview-1'));
    await user.click(screen.getByTestId('download-1'));
    expect(onPreview).toHaveBeenCalledWith(1);
    expect(onDownload).toHaveBeenCalledWith(1);
  });
});
