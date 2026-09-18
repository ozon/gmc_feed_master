import { apiGetText } from '../../api/client';

export async function downloadVersionXml(
  feedSourceId: number | string,
  version: number,
  xml?: string,
): Promise<void> {
  const content =
    xml ?? (await apiGetText(`/feed-sources/${feedSourceId}/export-history/${version}/content`));
  const url = URL.createObjectURL(new Blob([content], { type: 'application/xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `feed-${feedSourceId}-v${version}.xml`;
  anchor.click();
  URL.revokeObjectURL(url);
}
