import { useComputedColorScheme } from '@mantine/core';

export type TokenKind =
  | 'tag'
  | 'attr'
  | 'string'
  | 'comment'
  | 'cdata'
  | 'decl'
  | 'text'
  | 'entity';

export type Token = { text: string; kind: TokenKind };

const TOKEN_COLOR: Record<'light' | 'dark', Record<TokenKind, string>> = {
  light: {
    tag: '#1f6feb',
    attr: '#953800',
    string: '#0a7d33',
    comment: '#6e7781',
    cdata: '#8250df',
    decl: '#8250df',
    text: 'inherit',
    entity: '#cf222e',
  },
  dark: {
    tag: '#79c0ff',
    attr: '#ffa657',
    string: '#7ee787',
    comment: '#8b949e',
    cdata: '#d2a8ff',
    decl: '#d2a8ff',
    text: 'inherit',
    entity: '#ff7b72',
  },
};

const TAG_RE = /^(<\/?)([^\s/>]+)/;
const ATTR_RE = /(\s+)([^\s=/>]+)(\s*=\s*)("[^"]*"|'[^']*')?/g;

function pushText(tokens: Token[], text: string): void {
  if (!text) return;
  for (const part of text.split(/(&[^;\s]+;)/)) {
    if (!part) continue;
    tokens.push({
      text: part,
      kind: /^&[^;\s]+;$/.test(part) ? 'entity' : 'text',
    });
  }
}

function findTagEnd(xml: string, start: number): number {
  let quote: '"' | "'" | null = null;
  for (let i = start; i < xml.length; i += 1) {
    const ch = xml[i];
    if (quote !== null) {
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === '>') {
      return i;
    }
  }
  return -1;
}

function pushTag(tokens: Token[], segment: string): void {
  const open = TAG_RE.exec(segment);
  if (!open) {
    pushText(tokens, segment);
    return;
  }
  const rest = segment.slice(open[0].length);
  ATTR_RE.lastIndex = 0;
  let last = 0;
  let match: RegExpExecArray | null;
  const attrs: Token[] = [];
  while ((match = ATTR_RE.exec(rest))) {
    if (match.index > last) attrs.push({ text: rest.slice(last, match.index), kind: 'tag' });
    attrs.push({ text: match[1], kind: 'tag' });
    attrs.push({ text: match[2], kind: 'attr' });
    if (match[3]) attrs.push({ text: match[3], kind: 'tag' });
    if (match[4]) attrs.push({ text: match[4], kind: 'string' });
    last = match.index + match[0].length;
  }
  tokens.push({ text: open[0], kind: 'tag' });
  if (last < rest.length) attrs.push({ text: rest.slice(last), kind: 'tag' });
  tokens.push(...attrs);
}

// oxlint-disable-next-line react/only-export-components -- pure tokenizer is part of the XmlHighlight public interface; Fast Refresh does not apply to this utility module
export function tokenizeXml(xml: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < xml.length) {
    const lt = xml.indexOf('<', i);
    if (lt === -1) {
      pushText(tokens, xml.slice(i));
      break;
    }
    if (lt > i) pushText(tokens, xml.slice(i, lt));

    if (xml.startsWith('<!--', lt)) {
      const end = xml.indexOf('-->', lt + 4);
      const stop = end === -1 ? xml.length : end + 3;
      tokens.push({ text: xml.slice(lt, stop), kind: 'comment' });
      i = stop;
      continue;
    }
    if (xml.startsWith('<![CDATA[', lt)) {
      const end = xml.indexOf(']]>', lt + 9);
      const stop = end === -1 ? xml.length : end + 3;
      tokens.push({ text: xml.slice(lt, stop), kind: 'cdata' });
      i = stop;
      continue;
    }
    if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
      const end = xml.indexOf('>', lt);
      const stop = end === -1 ? xml.length : end + 1;
      tokens.push({ text: xml.slice(lt, stop), kind: 'decl' });
      i = stop;
      continue;
    }
    const gt = findTagEnd(xml, lt);
    if (gt === -1) {
      pushText(tokens, xml.slice(lt));
      break;
    }
    pushTag(tokens, xml.slice(lt, gt + 1));
    i = gt + 1;
  }
  return tokens;
}

// oxlint-disable-next-line react/only-export-components -- pure line-capper is part of the XmlHighlight public interface; Fast Refresh does not apply to this utility module
export function sliceXmlLines(
  xml: string,
  maxLines: number,
): { text: string; totalLines: number; truncated: boolean } {
  const lines = xml.split('\n');
  const totalLines = lines.length;
  const truncated = totalLines > maxLines;
  return {
    text: truncated ? lines.slice(0, maxLines).join('\n') : xml,
    totalLines,
    truncated,
  };
}

// oxlint-disable-next-line react/only-export-components -- pure formatter is part of the XmlHighlight public interface; Fast Refresh does not apply to this utility module
export function prettifyXml(xml: string, indent = '  '): string {
  const lines: string[] = [];
  let depth = 0;
  let i = 0;
  const pad = () => indent.repeat(Math.max(depth, 0));
  const pushTextLine = (text: string) => {
    const trimmed = text.trim();
    if (trimmed) lines.push(pad() + trimmed);
  };

  while (i < xml.length) {
    const lt = xml.indexOf('<', i);
    if (lt === -1) {
      pushTextLine(xml.slice(i));
      break;
    }
    if (lt > i) pushTextLine(xml.slice(i, lt));

    if (xml.startsWith('<!--', lt)) {
      const end = xml.indexOf('-->', lt + 4);
      const stop = end === -1 ? xml.length : end + 3;
      lines.push(pad() + xml.slice(lt, stop));
      i = stop;
      continue;
    }
    if (xml.startsWith('<![CDATA[', lt)) {
      const end = xml.indexOf(']]>', lt + 9);
      const stop = end === -1 ? xml.length : end + 3;
      lines.push(pad() + xml.slice(lt, stop));
      i = stop;
      continue;
    }
    if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
      const end = xml.indexOf('>', lt);
      const stop = end === -1 ? xml.length : end + 1;
      lines.push(pad() + xml.slice(lt, stop));
      i = stop;
      continue;
    }

    const gt = findTagEnd(xml, lt);
    if (gt === -1) {
      pushTextLine(xml.slice(lt));
      break;
    }
    const segment = xml.slice(lt, gt + 1);
    if (segment.startsWith('</')) {
      depth -= 1;
      lines.push(pad() + segment);
    } else {
      lines.push(pad() + segment);
      if (!segment.trimEnd().endsWith('/>')) depth += 1;
    }
    i = gt + 1;
  }

  return lines.join('\n');
}

export function XmlHighlight({ xml, maxLines }: { xml: string; maxLines?: number }) {
  const scheme = useComputedColorScheme('light');
  const colors = TOKEN_COLOR[scheme];
  const { text } = maxLines === undefined ? { text: xml } : sliceXmlLines(xml, maxLines);
  const lineCount = text.split('\n').length;
  return (
    <pre
      data-testid="xml-preview"
      style={{
        margin: 0,
        padding: 'var(--mantine-spacing-sm)',
        overflow: 'auto',
        fontSize: 'var(--mantine-font-size-xs)',
        lineHeight: 1.5,
      }}
    >
      <span
        data-testid="xml-line-numbers"
        aria-hidden
        style={{
          display: 'inline-block',
          verticalAlign: 'top',
          whiteSpace: 'pre',
          textAlign: 'right',
          userSelect: 'none',
          minWidth: `${String(lineCount).length}ch`,
          marginRight: '1ch',
          color: 'var(--mantine-color-dimmed)',
        }}
      >
        {Array.from({ length: lineCount }, (_, index) => index + 1).join('\n')}
      </span>
      <span style={{ display: 'inline-block', verticalAlign: 'top', whiteSpace: 'pre' }}>
        {tokenizeXml(text).map((token, index) => (
          // oxlint-disable-next-line react/no-array-index-key -- tokens are a deterministic, append-only list rendered once; positional keys are stable
          <span key={index} style={{ color: colors[token.kind] }}>
            {token.text}
          </span>
        ))}
      </span>
    </pre>
  );
}
