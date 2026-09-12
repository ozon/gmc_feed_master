import { useId } from 'react';
import { Box, Stack, Text, Textarea } from '@mantine/core';

export const PLACEHOLDER_RE = /\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}/g;

type Part = { text: string; name: string | null };

function splitParts(text: string): Part[] {
  const parts: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER_RE)) {
    const start = m.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), name: null });
    parts.push({ text: m[0], name: m[1] });
    last = start + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), name: null });
  return parts;
}

// ponytail: overlay assumes autosize (textarea never scrolls internally); add
// scroll-sync + maxRows if a height cap is ever set. Backdrop text is
// transparent so only the mark backgrounds show through.
const FONT = {
  fontFamily: 'var(--mantine-font-family)',
  fontSize: 'var(--mantine-font-size-sm)',
  lineHeight: 1.5,
  padding: '8px 12px',
  whiteSpace: 'pre-wrap',
  overflowWrap: 'break-word',
  wordBreak: 'break-word',
} as const;

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  known: Set<string>;
};

export function HighlightedTextarea({ label, value, onChange, known }: Props) {
  const id = useId();
  return (
    <Stack gap={4}>
      <Text component="label" htmlFor={id} size="sm" fw={500}>
        {label}
      </Text>
      <Box style={{ position: 'relative' }}>
        <Box
          aria-hidden
          style={{
            ...FONT,
            position: 'absolute',
            inset: 0,
            overflow: 'hidden',
            border: '1px solid transparent',
            borderRadius: 'var(--mantine-radius-sm)',
            color: 'transparent',
            pointerEvents: 'none',
          }}
        >
          {splitParts(value).map((part, i) =>
            part.name ? (
              <mark
                key={i}
                data-testid={`highlight-${part.name}`}
                style={{
                  background: known.has(part.name)
                    ? 'var(--mantine-color-yellow-light)'
                    : 'var(--mantine-color-red-light)',
                  color: 'transparent',
                  borderRadius: 2,
                }}
              >
                {part.text}
              </mark>
            ) : (
              <span key={i}>{part.text}</span>
            ),
          )}
          {'\n'}
        </Box>
        <Textarea
          id={id}
          autosize
          minRows={3}
          value={value}
          onChange={(e) => onChange(e.currentTarget.value)}
          styles={{ input: { ...FONT, background: 'transparent', position: 'relative' } }}
        />
      </Box>
    </Stack>
  );
}
