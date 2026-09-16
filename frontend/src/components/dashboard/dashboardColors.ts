// Single source for chart series colors — theme tokens so light/dark both resolve.
export const chartColors = {
  success: 'teal.6',
  error: 'red.6',
  warning: 'yellow.6',
  info: 'blue.6',
  raw: 'gray.6',
  exportable: 'teal.6',
  passed: 'blue.4',
  dropped: 'red.6',
  other: 'gray.6',
} as const;

// 8 slices max per spec (top feeds + Other); gray.6 reserved for Other.
export const donutPalette = [
  'blue.6',
  'indigo.6',
  'violet.6',
  'grape.6',
  'pink.6',
  'orange.6',
  'yellow.6',
  'lime.6',
] as const;
