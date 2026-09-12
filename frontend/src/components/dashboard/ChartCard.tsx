import { type ReactNode } from 'react';
import { Paper, Title } from '@mantine/core';
import { EmptyState } from '../StateViews';

export function ChartCard({
  title,
  isEmpty,
  emptyMessage,
  children,
}: {
  title: ReactNode;
  isEmpty: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  return (
    <Paper withBorder p="md" data-testid="chart-card">
      <Title order={5} mb="sm">
        {title}
      </Title>
      {isEmpty ? <EmptyState message={emptyMessage} /> : children}
    </Paper>
  );
}
