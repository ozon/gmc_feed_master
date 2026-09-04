import { Button, Stack, Title } from '@mantine/core';
import { IconGitCompare } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  useExportHistory,
  useExportVersionDiff,
  useFeedSource,
  useRollbackToVersion,
} from '../../api/hooks';
import { ExportUrlBlock } from '../../components/ExportUrlBlock';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifySuccess, notifyApiError } from '../../app/notifications';
import { ApiError } from '../../api/client';
import { ExportVersionList } from './ExportVersionList';
import { ExportVersionDiff } from './ExportVersionDiff';
import { RollbackConfirmModal } from './RollbackConfirmModal';

export function ExportPage() {
  const { t } = useTranslation('export');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const feed = useFeedSource(id);
  const history = useExportHistory(id);
  const rollback = useRollbackToVersion(id);
  const [versionA, setVersionA] = useState<number | undefined>();
  const [versionB, setVersionB] = useState<number | undefined>();
  const [compared, setCompared] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);

  const versions = useMemo(() => history.data ?? [], [history.data]);

  useEffect(() => {
    setCompared(false);
  }, [versionA, versionB]);

  const diff = useExportVersionDiff(id, compared ? versionA : undefined, compared ? versionB : undefined);

  if (feed.isPending || history.isPending) return <LoadingState />;
  if (feed.isError) return <ErrorState onRetry={() => void feed.refetch()} />;
  if (history.isError) return <ErrorState onRetry={() => void history.refetch()} />;
  if (!feed.data) return <EmptyState message={t('feedNotFound')} />;

  async function onConfirmRollback(version: number) {
    try {
      await rollback.mutateAsync(version);
      notifySuccess(t('rollbackSuccess', { version }));
      setRollbackTarget(null);
    } catch (error) {
      notifyApiError(
        error,
        t('rollbackFailed'),
        error instanceof ApiError && error.errors && error.errors.length > 0
          ? t('rollbackFailedWithErrors', { errors: error.errors.join('; ') })
          : undefined,
      );
    }
  }

  return (
    <Stack gap="md">
      <Title order={3}>{t('title')}</Title>
      {feed.data.export_url ? (
        <ExportUrlBlock
          feedSourceId={id}
          exportUrl={feed.data.export_url}
          onRotated={() => void feed.refetch()}
        />
      ) : null}
      {versions.length === 0 ? (
        <EmptyState message={t('versions.empty')} />
      ) : (
        <>
          <ExportVersionList
            versions={versions}
            versionA={versionA}
            versionB={versionB}
            onSelectA={setVersionA}
            onSelectB={setVersionB}
            onRollback={setRollbackTarget}
          />
          {versionA !== undefined && versionB !== undefined && !compared && (
            <Button
              leftSection={<IconGitCompare size={16} />}
              onClick={() => setCompared(true)}
              data-testid="compare-versions-button"
            >
              {t('compareVersions')}
            </Button>
          )}
          <ExportVersionDiff
            diff={diff.data}
            isPending={diff.isPending}
            isError={diff.isError}
            onRetry={() => void diff.refetch()}
          />
        </>
      )}
      <RollbackConfirmModal
        opened={rollbackTarget !== null}
        version={rollbackTarget}
        onClose={() => setRollbackTarget(null)}
        onConfirm={onConfirmRollback}
        pending={rollback.isPending}
      />
    </Stack>
  );
}