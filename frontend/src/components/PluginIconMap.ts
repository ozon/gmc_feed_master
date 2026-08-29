import { IconLetterA, IconLetterB, IconLetterC, IconLetterE, IconCircle } from '@tabler/icons-react';
import type { ComponentType } from 'react';

const MAP: Record<string, ComponentType<{ size?: number }>> = {
  'letter-e': IconLetterE,
  'letter-a': IconLetterA,
  'letter-b': IconLetterB,
  'letter-c': IconLetterC,
};

export function getPluginIcon(name: string | undefined): ComponentType<{ size?: number }> {
  if (!name) return IconCircle;
  return MAP[name] ?? IconCircle;
}
