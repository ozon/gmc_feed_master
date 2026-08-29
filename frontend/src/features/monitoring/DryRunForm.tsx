import { Button, Group, NumberInput } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UseMutationResult } from '@tanstack/react-query';

type DryRunInput = { limit: number };

type Props = {
  run: UseMutationResult<unknown, Error, DryRunInput>;
  onResult: (result: unknown, error?: unknown) => void;
};

export function DryRunForm({ run, onResult }: Props) {
  const { t } = useTranslation('monitoring');
  const [limit, setLimit] = useState<number>(100);
  async function onSubmit() {
    try {
      const result = await run.mutateAsync({ limit });
      onResult(result);
    } catch (error) {
      onResult(null, error);
    }
  }
  return (
    <Group align="end">
      <NumberInput
        label={t('dryRun.limitLabel')}
        description={t('dryRun.limitHelp')}
        value={limit}
        onChange={(value) => setLimit(typeof value === 'number' ? value : 100)}
        min={1}
        max={1000}
        data-testid="dry-run-limit"
      />
      <Button onClick={() => void onSubmit()} loading={run.isPending} data-testid="dry-run-submit">
        {t('dryRun.run')}
      </Button>
    </Group>
  );
}