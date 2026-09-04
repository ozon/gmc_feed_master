import { describe, expect, it } from 'vitest';
import { compileTemplate, parseIdList, renderPreview } from '../ids';

describe('parseIdList', () => {
  it('splits, trims, drops empties, dedupes', () => {
    expect(parseIdList('a,b\n c ,d\n')).toEqual(new Set(['a', 'b', 'c', 'd']));
    expect(parseIdList('a\na\n\n, ,b')).toEqual(new Set(['a', 'b']));
  });

  it('handles null/empty', () => {
    expect(parseIdList(null).size).toBe(0);
    expect(parseIdList('  \n,').size).toBe(0);
  });
});

describe('compileTemplate', () => {
  it('splits literals and tokens including subfield paths', () => {
    expect(compileTemplate('{brand} - Mid')).toEqual([
      { kind: 'tok', path: 'brand' },
      { kind: 'lit', text: ' - Mid' },
    ]);
    expect(compileTemplate('under {price.value}')).toEqual([
      { kind: 'lit', text: 'under ' },
      { kind: 'tok', path: 'price.value' },
    ]);
  });
});

describe('renderPreview', () => {
  it('renders tokens from the sample and keeps unknown tokens visible', () => {
    expect(renderPreview('{brand} - Mid')).toBe('Brand - Mid');
    expect(renderPreview('{nope} x')).toBe('{nope} x');
  });
});
