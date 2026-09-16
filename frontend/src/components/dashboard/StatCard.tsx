import { type ReactNode } from 'react';
import { Paper, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

const VARIANT_COLOR: Record<string, string> = {
  neutral: 'var(--mantine-color-text)',
  warning: 'var(--mantine-color-yellow-6)',
  critical: 'var(--mantine-color-red-6)',
};

export function StatCard({
  label,
  value,
  variant = 'neutral',
  suffix,
}: {
  label: ReactNode;
  value: number;
  variant?: 'neutral' | 'warning' | 'critical';
  suffix?: string;
}) {
  const { i18n } = useTranslation();
  return (
    <Paper withBorder p="md" data-variant={variant}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text
        ff="monospace"
        size="xl"
        c={VARIANT_COLOR[variant]}
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {new Intl.NumberFormat(i18n.language).format(value)}
        {suffix}
      </Text>
    </Paper>
  );
}
