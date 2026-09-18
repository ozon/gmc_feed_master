import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { FeedVersionPreviewModal } from './FeedVersionPreviewModal';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function xmlResponse(body: string) {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'application/xml' },
  });
}

describe('FeedVersionPreviewModal', () => {
  it('renders the fetched XML', async () => {
    stubFetch((url) =>
      url === '/feed-sources/1/export-history/2/content'
        ? xmlResponse('<g:id>A</g:id>')
        : new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    render(<FeedVersionPreviewModal feedSourceId={1} version={2} opened onClose={() => {}} />);
    expect(await screen.findByTestId('xml-preview')).toHaveTextContent('<g:id>A</g:id>');
  });

  it('shows the not-retained state on 404', async () => {
    stubFetch(() => new Response('gone', { status: 404 }));
    render(<FeedVersionPreviewModal feedSourceId={1} version={9} opened onClose={() => {}} />);
    expect(await screen.findByText(/no longer retained/i)).toBeInTheDocument();
  });
});
