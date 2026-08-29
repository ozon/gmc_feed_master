import { Button, Group, NumberInput } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useRunDryRun } from '../../api/hooks';

type Props = {
  feedSourceId: string;
  onResult: (result: unknown) => void;
};

export function DryRunForm({ feedSourceId, onResult }: Props) {
  const { t } = useTranslation('monitoring');
  const [limit, setLimit] = useState<number>(100);
  const run = useRunDryRun(feedSourceId);
  async function onSubmit() {
    const result = await run.mutateAsync({ limit });
    onResult(result);
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