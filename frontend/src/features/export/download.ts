import { apiGetText } from '../../api/client';

export function downloadXml(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'application/xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function downloadVersionXml(
  feedSourceId: number | string,
  version: number,
  xml?: string,
): Promise<void> {
  const content =
    xml ?? (await apiGetText(`/feed-sources/${feedSourceId}/export-history/${version}/content`));
  downloadXml(`feed-${feedSourceId}-v${version}.xml`, content);
}

export async function downloadLiveXml(
  feedSourceId: number | string,
  exportUrl: string,
): Promise<void> {
  const content = await apiGetText(exportUrl);
  downloadXml(`feed-${feedSourceId}.xml`, content);
}
