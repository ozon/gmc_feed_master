import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch } from '../../test/fetch';
import { downloadVersionXml } from './download';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('downloadVersionXml', () => {
  it('fetches when no xml is supplied and triggers an anchor download', async () => {
    stubFetch(
      () =>
        new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        }),
    );
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await downloadVersionXml(1, 2);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledOnce();
  });

  it('does not fetch when xml is supplied', async () => {
    const fetchMock = stubFetch(() => new Response('', { status: 200 }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await downloadVersionXml(1, 2, '<g:id>A</g:id>');

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
