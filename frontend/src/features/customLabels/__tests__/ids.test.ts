import { describe, expect, it } from 'vitest';
import {
  compileTemplate, formatIdList, parseIdEntries, parseIdList, parsePreviewLines, renderPreview,
} from '../ids';

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

describe('parseIdEntries', () => {
  it('preserves order and duplicates, drops empties', () => {
    expect(parseIdEntries('b, a\n\n a \nc,\n')).toEqual(['b', 'a', 'a', 'c']);
  });

  it('returns an empty array for empty input', () => {
    expect(parseIdEntries('')).toEqual([]);
    expect(parseIdEntries(undefined)).toEqual([]);
    expect(parseIdEntries(null)).toEqual([]);
  });
});

describe('parsePreviewLines', () => {
  it('makes one row per line; blank lines stay blank rows', () => {
    expect(parsePreviewLines('a\n\nb')).toEqual([['a'], [], ['b']]);
  });

  it('comma-splits each line into its IDs, trimmed, empty tokens dropped', () => {
    expect(parsePreviewLines('a, b ,\nc')).toEqual([['a', 'b'], ['c']]);
  });

  it('returns [] for empty or missing input', () => {
    expect(parsePreviewLines('')).toEqual([]);
    expect(parsePreviewLines(undefined)).toEqual([]);
    expect(parsePreviewLines(null)).toEqual([]);
  });
});

describe('formatIdList', () => {
  it('strips empties, splits commas to one per line, dedupes preserving order', () => {
    expect(formatIdList('b, a\n\n a \nc,\n')).toBe('b\na\nc');
  });

  it('returns an empty string for empty input', () => {
    expect(formatIdList('')).toBe('');
    expect(formatIdList('  \n, \n')).toBe('');
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
