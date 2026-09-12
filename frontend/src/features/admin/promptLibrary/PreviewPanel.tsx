import { useState } from 'react';
import { Button, Select, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/client';
import { usePreviewPromptTemplate } from '../../../api/hooks';

export function previewDetailErrors(error: unknown): string[] {
  if (error instanceof ApiError && error.detailObject) {
    const errors = (error.detailObject as { errors?: unknown }).errors;
    if (Array.isArray(errors)) {
      return errors.filter((e): e is string => typeof e === 'string');
    }
  }
  return [];
}

type Props = {
  base: Record<string, unknown>;
  feedOptions: { value: string; label: string }[];
};

export function PreviewPanel({ base, feedOptions }: Props) {
  const { t } = useTranslation('admin');
  const [feedId, setFeedId] = useState<string | null>(null);
  const preview = usePreviewPromptTemplate();

  return (
    <Stack gap="xs">
      <Select
        label={t('promptLibrary.preview.feedSource')}
        data={feedOptions}
        value={feedId}
        onChange={setFeedId}
      />
      <Button
        size="xs"
        disabled={!feedId || preview.isPending}
        onClick={() => preview.mutate({ ...base, feed_source_id: Number(feedId) })}
      >
        {t('promptLibrary.preview.run')}
      </Button>
      {preview.error ? (
        previewDetailErrors(preview.error).map((e) => (
          <Text key={e} c="red" size="sm">{e}</Text>
        ))
      ) : null}
      {preview.data ? (
        <Stack gap="xs">
          <Text size="sm">
            {t('promptLibrary.preview.usedVariables')}: {preview.data.used_variables.join(', ') || '—'}
          </Text>
          {preview.data.warnings.map((w) => (
            <Text key={w} c="orange" size="sm">{w}</Text>
          ))}
          {preview.data.messages.map((m, i) => (
            <pre key={i} data-testid={`preview-message-${m.role}`} style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
              {m.content}
            </pre>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}
