import {
  IconChartBar, IconCircle, IconDatabase, IconLetterA, IconLetterB, IconLetterC,
  IconLetterE, IconLink, IconListCheck, IconLock, IconMail, IconSettings,
  IconShield, IconSitemap, IconTag, IconTransform, IconWand,
} from '@tabler/icons-react';
import type { ComponentType } from 'react';

const MAP: Record<string, ComponentType<{ size?: number }>> = {
  'letter-e': IconLetterE,
  'letter-a': IconLetterA,
  'letter-b': IconLetterB,
  'letter-c': IconLetterC,
  'sitemap': IconSitemap,
  'list-check': IconListCheck,
  'cog': IconSettings,
  'database': IconDatabase,
  'tag': IconTag,
  'wand': IconWand,
  'shield': IconShield,
  'lock': IconLock,
  'link': IconLink,
  'mail': IconMail,
  'chart': IconChartBar,
  'transform': IconTransform,
};

export function getPluginIcon(name: string | undefined): ComponentType<{ size?: number }> {
  if (!name) return IconCircle;
  return MAP[name] ?? IconCircle;
}
