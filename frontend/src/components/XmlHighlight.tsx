import { useComputedColorScheme } from '@mantine/core';
import xmlGrammar from '@speed-highlight/core/languages/xml.js';
import { tokenizeWith, type ShjToken } from '@speed-highlight/core/tokenize';

export type Token = { text: string; type: ShjToken | undefined };

const TOKEN_COLOR: Record<'light' | 'dark', Partial<Record<ShjToken, string>>> = {
  light: {
    var: '#1f6feb',
    oper: '#1f6feb',
    class: '#953800',
    num: '#953800',
    str: '#0a7d33',
    cmnt: '#6e7781',
    esc: '#cf222e',
    err: '#cf222e',
  },
  dark: {
    var: '#79c0ff',
    oper: '#79c0ff',
    class: '#ffa657',
    num: '#ffa657',
    str: '#7ee787',
    cmnt: '#8b949e',
    esc: '#ff7b72',
    err: '#ff7b72',
  },
};

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

// oxlint-disable-next-line react/only-export-components -- pure tokenizer is part of the XmlHighlight public interface; Fast Refresh does not apply to this utility module
export function tokenizeXml(xml: string): Token[] {
  const tokens: Token[] = [];
  tokenizeWith(xml, xmlGrammar, (text, type) => {
    if (text) tokens.push({ text, type });
  });
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
          <span key={index} style={{ color: (token.type && colors[token.type]) || 'inherit' }}>
            {token.text}
          </span>
        ))}
      </span>
    </pre>
  );
}
