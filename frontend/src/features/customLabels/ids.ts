export function parseIdList(raw: string | undefined | null): Set<string> {
  if (!raw) return new Set();
  const ids = new Set<string>();
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) ids.add(trimmed);
  }
  return ids;
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
