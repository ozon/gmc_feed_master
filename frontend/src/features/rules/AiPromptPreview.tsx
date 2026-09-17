import { Alert, Modal, Stack, Text } from '@mantine/core';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useRuleAiPreview, type RuleAiPreviewRequest } from './hooks';

export type AiPromptPreviewProps = {
  opened: boolean;
  onClose: () => void;
  payload: RuleAiPreviewRequest;
};

export function AiPromptPreview({ opened, onClose, payload }: AiPromptPreviewProps) {
  const { t } = useTranslation('rules');
  const preview = useRuleAiPreview();
  const { mutate } = preview;

  useEffect(() => {
    if (opened) mutate(payload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  return (
    <Modal opened={opened} onClose={onClose} title={t('ai.previewTitle')} size="lg">
      <Stack gap="xs" data-testid="ai-preview">
        {(preview.data?.messages ?? []).map((message, index) => (
          <Text key={index} size="xs" style={{ whiteSpace: 'pre-wrap' }}>
            <strong>{message.role}</strong>: {message.content}
          </Text>
        ))}
        {(preview.data?.warnings ?? []).map((warning, index) => (
          <Alert key={`w-${index}`} color="orange" py={4}>{warning}</Alert>
        ))}
        {preview.isError ? <Alert color="red">{String(preview.error)}</Alert> : null}
      </Stack>
    </Modal>
  );
}
