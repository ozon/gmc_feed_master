import { useTranslation } from 'react-i18next';
import { useFeedSource } from '../../api/hooks';
import { ExportUrlBlock } from '../../components/ExportUrlBlock';
import { LoadingState, ErrorState } from '../../components/StateViews';

export function ExportUrlCard({ feedSourceId }: { feedSourceId: number | string }) {
  const { t } = useTranslation('common');
  const feedSource = useFeedSource(feedSourceId);

  if (feedSource.isPending) return <LoadingState />;
  if (feedSource.isError) {
    return <ErrorState onRetry={() => void feedSource.refetch()} />;
  }

  return (
    <ExportUrlBlock
      feedSourceId={feedSourceId}
      exportUrl={feedSource.data.export_url}
    />
  );
}
