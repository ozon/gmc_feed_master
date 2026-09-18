import { Button, Stack, Title } from '@mantine/core';
import { IconGitCompare } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router';
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
import { FeedVersionPreviewModal } from './FeedVersionPreviewModal';
import { downloadVersionXml } from './download';

function parseVersionParam(raw: string | null): number | undefined {
  if (raw === null || raw === '') return undefined;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export function ExportPage() {
  const { t } = useTranslation('export');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const feed = useFeedSource(id);
  const history = useExportHistory(id);
  const rollback = useRollbackToVersion(id);
  const [searchParams, setSearchParams] = useSearchParams();
  const [versionA, setVersionAState] = useState<number | undefined>(() =>
    parseVersionParam(searchParams.get('a')),
  );
  const [versionB, setVersionBState] = useState<number | undefined>(() =>
    parseVersionParam(searchParams.get('b')),
  );
  const [compared, setCompared] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);

  function setVersionA(value: number) {
    setVersionAState(value);
    const next = new URLSearchParams(searchParams);
    next.set('a', String(value));
    setSearchParams(next, { replace: true });
  }

  function setVersionB(value: number) {
    setVersionBState(value);
    const next = new URLSearchParams(searchParams);
    next.set('b', String(value));
    setSearchParams(next, { replace: true });
  }

  const versions = useMemo(() => history.data ?? [], [history.data]);

  const [prevVersions, setPrevVersions] = useState<[number | undefined, number | undefined]>([
    versionA,
    versionB,
  ]);
  if (prevVersions[0] !== versionA || prevVersions[1] !== versionB) {
    setPrevVersions([versionA, versionB]);
    setCompared(false);
  }

  const diff = useExportVersionDiff(
    id,
    compared ? versionA : undefined,
    compared ? versionB : undefined,
  );

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

  async function onDownload(version: number) {
    try {
      await downloadVersionXml(id, version);
    } catch (error) {
      notifyApiError(error, t('download.failed'));
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
            onPreview={setPreviewVersion}
            onDownload={(version) => void onDownload(version)}
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
            isPending={diff.isPending && diff.isFetching}
            isError={diff.isError}
            onRetry={() => void diff.refetch()}
            findingsA={versions.find((v) => v.version_number === versionA)?.findings}
            findingsB={versions.find((v) => v.version_number === versionB)?.findings}
          />
        </>
      )}
      <FeedVersionPreviewModal
        feedSourceId={id}
        version={previewVersion}
        opened={previewVersion !== null}
        onClose={() => setPreviewVersion(null)}
      />
      <RollbackConfirmModal
        opened={rollbackTarget !== null}
        version={rollbackTarget}
        onClose={() => setRollbackTarget(null)}
        onConfirm={(version) => void onConfirmRollback(version)}
        pending={rollback.isPending}
      />
    </Stack>
  );
}
