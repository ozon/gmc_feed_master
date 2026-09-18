import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { XmlHighlight, sliceXmlLines, tokenizeXml } from './XmlHighlight';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

describe('tokenizeXml', () => {
  it('splits tags, attributes, values and text', () => {
    const kinds = tokenizeXml('<g:id lang="de">A</g:id>');
    expect(kinds.some((t) => t.kind === 'tag' && t.text.includes('g:id'))).toBe(true);
    expect(kinds.some((t) => t.kind === 'attr' && t.text === 'lang')).toBe(true);
    expect(kinds.some((t) => t.kind === 'string' && t.text === '"de"')).toBe(true);
    expect(kinds.some((t) => t.kind === 'text' && t.text === 'A')).toBe(true);
  });

  it('classifies comments, CDATA, declarations and entities', () => {
    const kinds = tokenizeXml('<!--c--><![CDATA[x]]><?xml?>&amp;');
    expect(kinds.map((t) => t.kind)).toEqual(['comment', 'cdata', 'decl', 'entity']);
  });

  it('does not throw on an unmatched <', () => {
    expect(() => tokenizeXml('a < b')).not.toThrow();
    expect(tokenizeXml('a < b').some((t) => t.kind === 'text')).toBe(true);
  });
});

describe('sliceXmlLines', () => {
  it('caps lines and reports truncation', () => {
    const xml = 'l1\nl2\nl3';
    expect(sliceXmlLines(xml, 2)).toEqual({
      text: 'l1\nl2',
      totalLines: 3,
      truncated: true,
    });
    expect(sliceXmlLines(xml, 5)).toEqual({
      text: 'l1\nl2\nl3',
      totalLines: 3,
      truncated: false,
    });
  });
});

describe('XmlHighlight', () => {
  it('renders the raw XML as text content', () => {
    render(<XmlHighlight xml={'<g:id>A</g:id>'} />);
    expect(screen.getByTestId('xml-preview').textContent).toContain('<g:id>A</g:id>');
  });
});
