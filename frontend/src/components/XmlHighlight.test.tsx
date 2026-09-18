import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { XmlHighlight, prettifyXml, sliceXmlLines, tokenizeXml } from './XmlHighlight';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

describe('tokenizeXml', () => {
  it('splits tags, attributes, values and text via speed-highlight', () => {
    const tokens = tokenizeXml('<g:id lang="de">A</g:id>');
    expect(tokens.map((t) => t.text).join('')).toBe('<g:id lang="de">A</g:id>');
    expect(tokens.some((t) => t.type === 'var' && t.text === 'g:id')).toBe(true);
    expect(tokens.some((t) => t.type === 'class' && t.text === 'lang')).toBe(true);
    expect(tokens.some((t) => t.type === 'str' && t.text === '"de"')).toBe(true);
    expect(tokens.some((t) => t.type === undefined && t.text === 'A')).toBe(true);
  });

  it('classifies comments, CDATA, declarations and entities', () => {
    const tokens = tokenizeXml('<!--c--><![CDATA[x]]><?xml?>&amp;');
    expect(tokens).toContainEqual({ text: '<!--c-->', type: 'cmnt' });
    expect(tokens).toContainEqual({ text: '<![CDATA[x]]>', type: 'class' });
    expect(tokens).toContainEqual({ text: '<?', type: 'oper' });
    expect(tokens).toContainEqual({ text: 'xml', type: 'var' });
    expect(tokens).toContainEqual({ text: '&amp;', type: 'var' });
  });

  it('does not throw on an unmatched <', () => {
    expect(() => tokenizeXml('a < b')).not.toThrow();
    expect(tokenizeXml('a < b').some((t) => t.type === undefined)).toBe(true);
  });

  it('keeps quoted ">" inside a tag', () => {
    const xml = '<g:id content="a > b">x</g:id>';
    const tokens = tokenizeXml(xml);
    expect(tokens.map((t) => t.text).join('')).toBe(xml);
    expect(tokens.some((t) => t.type === 'str' && t.text === '"a > b"')).toBe(true);
    expect(tokens.some((t) => t.type === undefined && t.text === 'x')).toBe(true);
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

describe('prettifyXml', () => {
  it('indents nested elements, one per line, with text on its own line', () => {
    expect(prettifyXml('<a><b>x</b></a>')).toBe('<a>\n  <b>\n    x\n  </b>\n</a>');
  });

  it('keeps self-closing tags on one line', () => {
    expect(prettifyXml('<a><b/></a>')).toBe('<a>\n  <b/>\n</a>');
  });

  it('indents comments, declarations and CDATA', () => {
    expect(prettifyXml('<?xml version="1.0"?><r><!--c--><![CDATA[d]]></r>')).toBe(
      '<?xml version="1.0"?>\n<r>\n  <!--c-->\n  <![CDATA[d]]>\n</r>',
    );
  });

  it('drops whitespace-only text nodes', () => {
    expect(prettifyXml('<a>\n  <b/>\n</a>')).toBe('<a>\n  <b/>\n</a>');
  });

  it('does not split on a quoted ">"', () => {
    expect(prettifyXml('<a x="1 > 2"><b/></a>')).toBe('<a x="1 > 2">\n  <b/>\n</a>');
  });

  it('never throws on malformed input', () => {
    expect(() => prettifyXml('a < b')).not.toThrow();
    expect(prettifyXml('')).toBe('');
  });
});

describe('XmlHighlight', () => {
  it('renders the raw XML as text content', () => {
    render(<XmlHighlight xml={'<g:id>A</g:id>'} />);
    expect(screen.getByTestId('xml-preview').textContent).toContain('<g:id>A</g:id>');
  });

  it('renders one line-number per line in a dimmed gutter', () => {
    render(<XmlHighlight xml={'<g:id>A</g:id>\n<g:id>B</g:id>\n<g:id>C</g:id>'} />);
    const gutter = screen.getByTestId('xml-line-numbers');
    expect(gutter).toHaveAttribute('aria-hidden', 'true');
    expect(gutter.textContent?.split('\n')).toEqual(['1', '2', '3']);
  });
});
