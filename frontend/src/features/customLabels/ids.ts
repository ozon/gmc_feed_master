/** Ordered, trimmed, empty-dropped entries WITHOUT dedupe — row i of the
 * product preview aligns with entry i. */
export function parseIdEntries(raw: string | undefined | null): string[] {
  if (!raw) return [];
  const entries: string[] = [];
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) entries.push(trimmed);
  }
  return entries;
}

export function parseIdList(raw: string | undefined | null): Set<string> {
  if (!raw) return new Set();
  const ids = new Set<string>();
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) ids.add(trimmed);
  }
  return ids;
}

/** One preview row per textarea LINE: row i = line i (blank lines render
 * blank rows, so line↔row alignment never breaks). A line's comma groups
 * are its IDs; the line's first ID drives its preview-row match display. */
export function parsePreviewLines(raw: string | undefined | null): string[][] {
  if (!raw) return [];
  return raw.split('\n').map((line) =>
    line.split(',').map((part) => part.trim()).filter((part) => part !== ''),
  );
}

/** Normalize a value list: trim, strip empty lines, split comma groups to
 * one ID per line, dedupe preserving first-occurrence order. */
export function formatIdList(raw: string): string {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const ids of parsePreviewLines(raw)) {
    for (const id of ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out.join('\n');
}

export type TemplateSegment = { kind: 'lit'; text: string } | { kind: 'tok'; path: string };

export function compileTemplate(template: string): TemplateSegment[] {
  const segments: TemplateSegment[] = [];
  let pos = 0;
  for (const match of template.matchAll(/\{([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\}/g)) {
    if (match.index > pos) segments.push({ kind: 'lit', text: template.slice(pos, match.index) });
    segments.push({ kind: 'tok', path: match[1] });
    pos = match.index + match[0].length;
  }
  if (pos < template.length) segments.push({ kind: 'lit', text: template.slice(pos) });
  return segments;
}

export function renderPreview(
  template: string,
  sample: Record<string, unknown> = { brand: 'Brand', id: '123' },
): string {
  return compileTemplate(template)
    .map((seg) => (seg.kind === 'lit' ? seg.text : String(sample[seg.path] ?? `{${seg.path}}`)))
    .join('');
}
