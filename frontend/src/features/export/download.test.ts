import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch } from '../../test/fetch';
import { downloadLiveXml, downloadVersionXml } from './download';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubUrlApi(returnedUrl = 'blob:http://localhost/abc') {
  const blobs: Blob[] = [];
  const createObjectURL = vi
    .spyOn(URL, 'createObjectURL')
    .mockImplementation((obj: Blob | MediaSource) => {
      if (obj instanceof Blob) blobs.push(obj);
      return returnedUrl;
    });
  const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  let clicked: HTMLAnchorElement | undefined;
  const createElement = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(
    (tagName: string, options?: ElementCreationOptions) => {
      const element = createElement(tagName, options);
      if (element instanceof HTMLAnchorElement) clicked = element;
      return element;
    },
  );
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  return {
    blobs,
    createObjectURL,
    revokeObjectURL,
    click,
    getClicked: () => clicked,
  };
}

describe('downloadVersionXml', () => {
  it('fetches when no xml is supplied and downloads it through an anchor', async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch(
      () =>
        new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        }),
    );
    const urlApi = stubUrlApi();

    await downloadVersionXml(1, 2);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(urlApi.createObjectURL).toHaveBeenCalledOnce();
    expect(urlApi.blobs).toHaveLength(1);
    expect(urlApi.blobs[0].type).toBe('application/xml');
    expect(await urlApi.blobs[0].text()).toBe('<g:id>A</g:id>');

    const anchor = urlApi.getClicked();
    expect(anchor?.download).toBe('feed-1-v2.xml');
    expect(anchor?.href).toBe('blob:http://localhost/abc');

    expect(urlApi.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(urlApi.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/abc');
  });

  it('downloads the supplied xml without fetching and revokes on a later tick', async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch(() => new Response('', { status: 200 }));
    const urlApi = stubUrlApi();

    await downloadVersionXml(1, 2, '<g:id>B</g:id>');

    expect(fetchMock).not.toHaveBeenCalled();
    expect(urlApi.blobs).toHaveLength(1);
    expect(urlApi.blobs[0].type).toBe('application/xml');
    expect(await urlApi.blobs[0].text()).toBe('<g:id>B</g:id>');
    expect(urlApi.getClicked()?.download).toBe('feed-1-v2.xml');
    expect(urlApi.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(urlApi.revokeObjectURL).toHaveBeenCalledOnce();
  });
});

describe('downloadLiveXml', () => {
  it('fetches the public export URL and downloads it as feed-{id}.xml', async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch(
      () =>
        new Response('<g:id>Live</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        }),
    );
    const urlApi = stubUrlApi();

    await downloadLiveXml(1, 'http://localhost/export/abc.xml');

    expect(fetchMock).toHaveBeenCalledWith('http://localhost/export/abc.xml', expect.anything());
    expect(await urlApi.blobs[0].text()).toBe('<g:id>Live</g:id>');
    expect(urlApi.getClicked()?.download).toBe('feed-1.xml');
    vi.runAllTimers();
    expect(urlApi.revokeObjectURL).toHaveBeenCalledOnce();
  });
});
